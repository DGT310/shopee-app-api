from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json

app = Flask(__name__)

# === Test Environment Credentials ===
PARTNER_ID = 1190367
PARTNER_KEY = "shpk6f5070654e5a774a5a684f63776e7a53454e7049655767636b6a46466743"
HOST = "https://partner.test-stable.shopeemobile.com"

@app.route("/")
def home():
    return "✅ Shopee Flask Test Server Running OK"

@app.route("/callback")
def callback():
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return jsonify({"error": "❌ Missing code or shop_id"}), 400

    # === Step 1. Build signature ===
    path = "/api/v2/auth/token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}"
    sign = hmac.new(PARTNER_KEY.encode(), base_string.encode(), hashlib.sha256).hexdigest()

    # === Step 2. Call Shopee API ===
    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }

    res = requests.post(url, json=payload)
    try:
        api_response = res.json()
    except:
        api_response = {"raw_response": res.text}

    debug = {
        "api_response": api_response,
        "debug_base_string": base_string,
        "debug_sign": sign,
        "raw_query": f"code={code}&shop_id={shop_id}"
    }

    return jsonify(debug)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


