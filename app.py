from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
HOST = "https://partner.shopeemobile.com"

# === ROUTES ===

@app.route("/")
def home():
    return "✅ Shopee Flask Server Running OK (Live Mode)"

@app.route("/callback")
def callback():
    """Shopee redirects here with ?code=...&shop_id=..."""
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return "❌ Missing code or shop_id from Shopee redirect.", 400

    # Step 1: Generate sign
    path = "/api/v2/auth/token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}"

    sign = hmac.new(
        PARTNER_KEY.encode(),
        base_string.encode(),
        hashlib.sha256
    ).hexdigest()

    # Step 2: Request access token
    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }

    res = requests.post(url, json=payload)
    try:
        data = res.json()
    except Exception:
        data = {"raw": res.text}

    print("🔗 URL:", url)
    print("📦 Payload:", payload)
    print("🧾 Response:", json.dumps(data, indent=2))

    # Step 3: Return the result
    return jsonify({
        "status": "success",
        "message": "Shopee token exchange complete!",
        "request_id": data.get("request_id"),
        "response": data
    })

# For Render health check
@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
