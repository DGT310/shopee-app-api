from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
HOST = "https://partner.shopeemobile.com"

@app.route("/")
def home():
    return "✅ Shopee Flask Server Running OK (Live Mode)"

def hmac_sha256_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

def token_request(code_to_use: str, shop_id: int, timestamp: int):
    PATH = "/api/v2/auth/token/get"
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{code_to_use}"  # <- REQUIRED for token/get
    sign = hmac_sha256_hex(PARTNER_KEY, base_string)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "code": code_to_use,        # MUST match what was used in base_string
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
    candidates = []
    # 1) Use RAW code as-is (common success case)
    candidates.append(("RAW", raw_code))
    # 2) If hex-like, try decoded ASCII too
    try:
        decoded = bytes.fromhex(raw_code).decode("utf-8")
        if decoded and decoded != raw_code:
            candidates.append(("HEX→ASCII", decoded))
    except Exception:
        pass

    timestamp = int(time.time())  # keep single timestamp

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
        # Success fast-path
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

        # If Shopee says wrong sign, try next variant automatically
        if isinstance(data, dict) and data.get("error") != "error_sign":
            # Not a sign error -> no point trying the other variant further
            break

    # If we got here, all attempts failed
    return jsonify({
        "message": "❌ Shopee token exchange failed",
        "shop_id": shop_id,
        "attempts": attempts  # includes base_string & sign for each variant
    }), 400

# Health check
@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
