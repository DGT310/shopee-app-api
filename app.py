from flask import Flask, request, redirect, jsonify
import time, hmac, hashlib, requests, os, json

app = Flask(__name__)

# === CONFIGURATION ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"   # <-- replace with your real partner key
SHOP_ID = 706762797
HOST = "https://partner.shopeemobile.com"

# Change to your Render URL later
REDIRECT_URL = "https://shopee-app-api.onrender.com/callback"

TOKEN_FILE = "tokens.json"

def save_tokens(data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f)

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return {}
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)

@app.route("/")
def home():
    return "✅ Shopee Flask API Server Running"

@app.route("/authorize")
def authorize():
    path = "/api/v2/shop/auth_partner"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(PARTNER_KEY.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&redirect={REDIRECT_URL}"
    return redirect(url)

@app.route("/callback")
def callback():
    raw_query = request.query_string.decode("utf-8")
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return jsonify({"error": "Missing code or shop_id", "raw_query": raw_query})

    path = "/api/v2/auth/token/get"
    timestamp = int(time.time())

    # ✅ Keep code exactly as Shopee sends it, do not alter or re-encode
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}{shop_id}"
    sign = hmac.new(PARTNER_KEY.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"

    payload = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }

    headers = {"Content-Type": "application/json"}
    res = requests.post(url, json=payload, headers=headers).json()

    save_tokens(res)
    return jsonify({
        "debug_base_string": base_string,
        "debug_sign": sign,
        "api_response": res,
        "raw_query": raw_query
    })


@app.route("/refresh_token")
def refresh_token():
    data = load_tokens()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return "❌ No refresh_token found."

    path = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(PARTNER_KEY.encode(), base_string.encode(), hashlib.sha256).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "partner_id": PARTNER_ID,
        "shop_id": SHOP_ID,
        "refresh_token": refresh_token
    }
    res = requests.post(url, json=payload).json()
    save_tokens(res)
    return jsonify(res)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)



