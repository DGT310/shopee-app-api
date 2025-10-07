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
    import requests, hmac, hashlib, time, json

    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return "❌ Missing code or shop_id", 400

    # === Shopee Live App Credentials ===
    PARTNER_ID = 2013146
    PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
    HOST = "https://partner.shopeemobile.com"
    PATH = "/api/v2/auth/token/get"

    # === Step 1: Use correct UTC timestamp ===
    timestamp = int(time.time())  # Render is UTC, this is correct

    # === Step 2: Build correct base string ===
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{code}"

    # === Step 3: Generate HMAC-SHA256 signature ===
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    print("🔹Base string:", base_string)
    print("🔹Sign:", sign)

    # === Step 4: Build request URL ===
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"

    # === Step 5: Request access token ===
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

    print("🧾 Response:", json.dumps(data, indent=2))
    return data

# For Render health check
@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

