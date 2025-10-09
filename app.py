from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json, threading, os

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
HOST = "https://partner.shopeemobile.com"

# === FILE TO STORE TOKENS ===
TOKEN_FILE = "/mnt/data/tokens.json"  # Render persistent storage path


# ---------- TOKEN STORAGE ----------

def load_tokens():
    """Load saved tokens from file"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                print("🔹 Loaded tokens from file:", data)
                return data
        except Exception as e:
            print("⚠️ Could not load tokens:", e)
    return {"shop_id": None, "access_token": None, "refresh_token": None, "last_refresh": None}


def save_tokens(data):
    """Save tokens to file"""
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print("💾 Tokens saved:", data)
    except Exception as e:
        print("⚠️ Failed to save tokens:", e)


# Global in-memory cache
TOKENS = load_tokens()


# ---------- UTILITIES ----------

def hmac_sha256_hex(key: str, msg: str) -> str:
    """Generate HMAC SHA256 signature (Shopee requirement)"""
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------- AUTH: GET TOKEN (CALLBACK) ----------

def token_request(code_to_use: str, shop_id: int, timestamp: int):
    PATH = "/api/v2/auth/token/get"
    base_string = f"{PARTNER_ID}{PATH}{timestamp}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "code": code_to_use,
        "shop_id": shop_id,
        "partner_id": PARTNER_ID
    }
    return url, payload, base_string, sign


@app.route("/callback")
def callback():
    """Handle Shopee redirect and exchange code for access token"""
    raw_code = request.args.get("code") or ""
    shop_id = request.args.get("shop_id")

    if not raw_code or not shop_id:
        return "❌ Missing code or shop_id", 400

    timestamp = int(time.time())
    url, payload, base_string, sign = token_request(raw_code, int(shop_id), timestamp)
    res = requests.post(url, json=payload, timeout=20)
    data = res.json()

    if "access_token" in data:
        TOKENS.update({
            "shop_id": int(shop_id),
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "last_refresh": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        })
        save_tokens(TOKENS)

        return jsonify({
            "message": "✅ Shopee token exchange success",
            "shop_id": shop_id,
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "request_id": data.get("request_id"),
            "debug": {"base_string": base_string, "sign": sign}
        })
    else:
        return jsonify({"error": data}), 400


# ---------- REFRESH TOKEN ENDPOINT ----------

@app.route("/refresh_token")
def refresh_token():
    """Exchange a refresh_token for a new access_token"""
    refresh_token = request.args.get("refresh_token") or TOKENS.get("refresh_token")
    shop_id = request.args.get("shop_id") or TOKENS.get("shop_id")

    if not refresh_token or not shop_id:
        return jsonify({"error": "Missing refresh_token or shop_id"}), 400

    PATH = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{refresh_token}{shop_id}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "partner_id": PARTNER_ID,
        "shop_id": int(shop_id),
        "refresh_token": refresh_token
    }

    res = requests.post(url, json=payload, timeout=20)
    data = res.json()

    if "access_token" in data:
        TOKENS.update({
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "last_refresh": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        })
        save_tokens(TOKENS)

    return jsonify({
        "message": "✅ Shopee access token refreshed" if "access_token" in data else "❌ Failed to refresh token",
        "response": data,
        "debug": {"base_string": base_string, "sign": sign}
    })


# ---------- TEST API ----------

@app.route("/test_api")
def test_api():
    """Test Shopee API using current access_token"""
    access_token = request.args.get("access_token") or TOKENS.get("access_token")
    shop_id = request.args.get("shop_id") or TOKENS.get("shop_id")

    if not access_token or not shop_id:
        return jsonify({"error": "Missing access_token or shop_id"}), 400

    PATH = "/api/v2/shop/get_shop_info"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{access_token}{shop_id}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&access_token={access_token}&shop_id={shop_id}"
    res = requests.get(url, timeout=20)
    data = res.json()

    return jsonify({
        "message": "✅ Shopee API call success" if "response" in data else "⚠️ API call failed",
        "response": data
    })


# ---------- AUTO REFRESH BACKGROUND TASK ----------

def auto_refresh_loop():
    """Automatically refresh tokens every 3 hours"""
    while True:
        if TOKENS.get("refresh_token") and TOKENS.get("shop_id"):
            print("🔄 Auto-refreshing Shopee token...")
            try:
                res = requests.get("http://127.0.0.1:10000/refresh_token", timeout=30)
                print("✅ Auto-refresh done at", time.strftime("%Y-%m-%d %H:%M:%S"))
                print("Response:", res.text)
            except Exception as e:
                print("⚠️ Auto-refresh error:", e)
        time.sleep(3 * 3600)


# ---------- HEALTH ----------

@app.route("/")
def home():
    return jsonify({
        "status": "✅ Shopee Flask Server Running OK (Live Mode)",
        "tokens": TOKENS
    })


@app.route("/ping")
def ping():
    return "pong", 200


# ---------- START ----------

if __name__ == "__main__":
    threading.Thread(target=auto_refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
