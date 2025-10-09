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
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print("💾 Tokens saved:", data)
    except Exception as e:
        print("⚠️ Failed to save tokens:", e)


TOKENS = load_tokens()


# ---------- UTILITIES ----------

def hmac_sha256_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------- AUTH: GET TOKEN ----------

def token_request(code_to_use: str, shop_id: int, timestamp: int):
    PATH = "/api/v2/auth/token/get"
    base_string = f"{PARTNER_ID}{PATH}{timestamp}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {"code": code_to_use, "shop_id": shop_id, "partner_id": PARTNER_ID}
    return url, payload, base_string, sign


@app.route("/callback")
def callback():
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
    return jsonify({"error": data}), 400


# ---------- REFRESH TOKEN ----------

@app.route("/refresh_token")
def refresh_token():
    refresh_token = request.args.get("refresh_token") or TOKENS.get("refresh_token")
    shop_id = request.args.get("shop_id") or TOKENS.get("shop_id")
    if not refresh_token or not shop_id:
        return jsonify({"error": "Missing refresh_token or shop_id"}), 400

    PATH = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{refresh_token}{shop_id}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {"partner_id": PARTNER_ID, "shop_id": int(shop_id), "refresh_token": refresh_token}

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


# ---------- POWER BI SALES DATA ----------

@app.route("/sales_data")
def sales_data():
    """Return last 7 days of Shopee orders (for Power BI)"""
    access_token = TOKENS.get("access_token")
    shop_id = TOKENS.get("shop_id")
    if not access_token or not shop_id:
        print("❌ Token missing. TOKENS =", TOKENS)
        return jsonify({"error": "Token missing, please reauthorize"}), 400

    PATH = "/api/v2/order/get_order_list"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{access_token}{shop_id}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&access_token={access_token}&shop_id={shop_id}"

    payload = {
        "time_range_field": "create_time",
        "time_from": int(time.time()) - 7 * 24 * 3600,
        "time_to": int(time.time()),
        "page_size": 50
    }

    print("🔹 Fetching Shopee orders:", url)
    print("🔹 Payload:", payload)

    try:
        res = requests.post(url, json=payload, timeout=30)
        print("🔹 Shopee HTTP Status:", res.status_code)
        data = res.json()
        print("🔹 Shopee Response:", data)
    except Exception as e:
        print("⚠️ Error contacting Shopee:", e)
        return jsonify({"error": f"Request to Shopee failed: {str(e)}"}), 500

    # --- Defensive checks ---
    if not isinstance(data, dict):
        print("⚠️ Non-JSON response from Shopee:", data)
        return jsonify({"error": "Shopee returned non-JSON", "raw": str(data)}), 500
    if data.get("error"):
        print("⚠️ Shopee API error:", data)
        return jsonify({
            "error": f"Shopee API error: {data.get('message', 'unknown')}",
            "raw": data
        }), 500
    if "response" not in data or "order_list" not in data["response"]:
        print("⚠️ Missing expected fields in Shopee response:", data)
        return jsonify({
            "error": "Shopee API response missing expected fields",
            "raw": data
        }), 500

    orders = data["response"].get("order_list", [])
    clean = []
    for o in orders:
        clean.append({
            "order_sn": o.get("order_sn"),
            "region": o.get("region"),
            "status": o.get("order_status"),
            "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(o.get("create_time", 0))),
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(o.get("update_time", 0))),
            "total_amount": o.get("total_amount", 0)
        })

    print(f"✅ Returning {len(clean)} orders to Power BI.")
    return jsonify(clean)


# ---------- AUTO REFRESH BACKGROUND TASK ----------

def auto_refresh_loop():
    while True:
        if TOKENS.get("refresh_token") and TOKENS.get("shop_id"):
            print("🔄 Auto-refreshing Shopee token...")
            try:
                res = requests.get("http://127.0.0.1:10000/refresh_token", timeout=30)
                print("✅ Auto-refresh done at", time.strftime("%Y-%m-%d %H:%M:%S"))
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

