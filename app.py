from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
HOST = "https://partner.shopeemobile.com"


# ---------- UTILITIES ----------

def hmac_sha256_hex(key: str, msg: str) -> str:
    """Generate HMAC SHA256 signature (Shopee requirement)"""
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


# ---------- AUTH: GET TOKEN (CALLBACK) ----------

def token_request(code_to_use: str, shop_id: int, timestamp: int):
    PATH = "/api/v2/auth/token/get"
    # ✅ Correct base string (no code)
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

    # Prepare both representations
    candidates = [("RAW", raw_code)]
    try:
        decoded = bytes.fromhex(raw_code).decode("utf-8")
        if decoded and decoded != raw_code:
            candidates.append(("HEX→ASCII", decoded))
    except Exception:
        pass

    timestamp = int(time.time())
    attempts = []

    for label, candidate_code in candidates:
        url, payload, base_string, sign = token_request(candidate_code, int(shop_id), timestamp)
        res = requests.post(url, json=payload, timeout=20)
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}

        attempts.append({
            "label": label,
            "used_code": candidate_code,
            "base_string": base_string,
            "sign": sign,
            "status": res.status_code,
            "response": data
        })

        if isinstance(data, dict) and data.get("access_token"):
            return jsonify({
                "message": "✅ Shopee token exchange success",
                "variant": label,
                "request_id": data.get("request_id"),
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "shop_id": shop_id,
                "debug": {"base_string": base_string, "sign": sign}
            }), 200

        if isinstance(data, dict) and data.get("error") != "error_sign":
            break

    return jsonify({
        "message": "❌ Shopee token exchange failed",
        "shop_id": shop_id,
        "attempts": attempts
    }), 400


# ---------- REFRESH TOKEN ENDPOINT ----------

@app.route("/refresh_token")
def refresh_token():
    """Exchange a refresh_token for a new access_token"""
    refresh_token = request.args.get("refresh_token")
    shop_id = request.args.get("shop_id")

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

    try:
        res = requests.post(url, json=payload, timeout=20)
        data = res.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "message": "✅ Shopee access token refreshed" if "access_token" in data else "❌ Failed to refresh token",
        "request_id": data.get("request_id"),
        "response": data,
        "debug": {"base_string": base_string, "sign": sign, "url": url}
    })


# ---------- TEST LIVE API CALL ----------

@app.route("/test_api")
def test_api():
    """Test live Shopee API using an access_token"""
    access_token = request.args.get("access_token")
    shop_id = request.args.get("shop_id")

    if not access_token or not shop_id:
        return jsonify({"error": "Missing access_token or shop_id"}), 400

    PATH = "/api/v2/shop/get_shop_info"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{access_token}{shop_id}"
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&access_token={access_token}&shop_id={shop_id}"

    try:
        res = requests.get(url, timeout=20)
        data = res.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "message": "✅ Shopee API call success" if data.get("response") else "⚠️ API call returned error",
        "url": url,
        "response": data
    })


# ---------- HEALTH CHECK ----------

@app.route("/")
def home():
    return "✅ Shopee Flask Server Running OK (Live Mode)"


@app.route("/ping")
def ping():
    return "pong", 200


# ---------- RUN SERVER ----------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
