from flask import Flask, request, jsonify
import requests, hmac, hashlib, time, json, binascii

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
HOST = "https://partner.shopeemobile.com"

@app.route("/")
def home():
    return "✅ Shopee Flask Server Running OK (Live Mode)"

@app.route("/callback")
def callback():
    """Handle Shopee redirect and exchange code for access token"""
    raw_code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not raw_code or not shop_id:
        return "❌ Missing code or shop_id", 400

    # --- Try decoding Shopee's hex-encoded code ---
    try:
        code = bytes.fromhex(raw_code).decode()
        print(f"🧩 Code was hex-encoded, decoded to: {code}")
    except Exception:
        code = raw_code
        print(f"🧩 Code used as raw text: {code}")

    # --- Build the token exchange request ---
    PATH = "/api/v2/auth/token/get"
    timestamp = int(time.time())  # UTC timestamp

    # === Step 1: Build base string ===
    base_string = f"{PARTNER_ID}{PATH}{timestamp}{code}"
    print("🔹Base string:", base_string)

    # === Step 2: Generate HMAC-SHA256 signature ===
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    print("🔹Sign:", sign)

    # === Step 3: Build request URL ===
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"

    # === Step 4: Request access token ===
    payload = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }

    print("📦 Payload:", json.dumps(payload, indent=2))

    res = requests.post(url, json=payload)
    try:
        data = res.json()
    except Exception:
        data = {"raw": res.text}

    print("🧾 Response:", json.dumps(data, indent=2))

    # === Step 5: Return response to browser ===
    return jsonify({
        "message": "Shopee token exchange complete!",
        "request_id": data.get("request_id"),
        "response": data
    })

# Health check route for Render
@app.route("/ping")
def ping():
    return "pong", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
