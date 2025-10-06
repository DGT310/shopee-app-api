from flask import Flask, request, redirect, jsonify
import time, hmac, hashlib, requests, os, json, binascii

app = Flask(__name__)

# === CONFIGURATION (LIVE MODE) ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
SHOP_ID = 706762797
HOST = "https://partner.shopeemobile.com"

# ✅ Must exactly match your Shopee App setting
REDIRECT_URL = "https://shopee-app-api.onrender.com/callback"

TOKEN_FILE = "tokens.json"


# === Utility: Save / Load token ===
def save_tokens(data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return {}
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


# === Utility: Get Shopee LIVE server time ===
def get_shopee_timestamp():
    """
    Use live Shopee time API; if not available, use local system time (+2 s offset).
    """
    try:
        url = "https://partner.shopeemobile.com/api/v2/public/get_shopee_time"
        res = requests.get(url, timeout=5).json()
        if "timestamp" in res:
            ts = int(res["timestamp"])
            print(f"✅ Using Shopee LIVE time: {ts}")
            return ts
        print("⚠️ Shopee LIVE time API returned:", res)
    except Exception as e:
        print(f"⚠️ Cannot fetch Shopee LIVE time: {e}")
    local_ts = int(time.time()) + 2
    print(f"⚠️ Using local system time (fallback): {local_ts}")
    return local_ts


@app.route("/")
def home():
    return "✅ Shopee Flask API Server Running (LIVE Mode)"


# === STEP 1: Authorize shop ===
@app.route("/authorize")
def authorize():
    path = "/api/v2/shop/auth_partner"
    timestamp = get_shopee_timestamp()

    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(
        PARTNER_KEY.encode(),
        base_string.encode(),
        hashlib.sha256
    ).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&redirect={REDIRECT_URL}"
    print("🔗 Auth URL:", url)
    return redirect(url)


# === STEP 2: Callback from Shopee ===
@app.route("/callback")
def callback():
    raw_query = request.query_string.decode("utf-8")
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return jsonify({"error": "Missing code or shop_id", "raw_query": raw_query})

    # Decode hex if needed
    try:
        if all(c in "0123456789abcdefABCDEF" for c in code):
            code = binascii.unhexlify(code).decode("utf-8")
    except Exception:
        pass

    time.sleep(2)

    path = "/api/v2/auth/token/get"
    timestamp = get_shopee_timestamp()
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}"
    sign = hmac.new(
        PARTNER_KEY.encode(),
        base_string.encode(),
        hashlib.sha256
    ).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {"code": code, "shop_id": int(shop_id), "partner_id": PARTNER_ID}
    headers = {"Content-Type": "application/json"}

    res = requests.post(url, json=payload, headers=headers).json()
    save_tokens(res)

    return jsonify({
        "decoded_code": code,
        "debug_base_string": base_string,
        "debug_sign": sign,
        "api_response": res,
        "raw_query": raw_query
    })


# === STEP 3: Refresh token ===
@app.route("/refresh_token")
def refresh_token():
    data = load_tokens()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return jsonify({"error": "❌ No refresh_token found."})

    path = "/api/v2/auth/access_token/get"
    timestamp = get_shopee_timestamp()
    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(
        PARTNER_KEY.encode(),
        base_string.encode(),
        hashlib.sha256
    ).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"
    payload = {
        "partner_id": PARTNER_ID,
        "shop_id": SHOP_ID,
        "refresh_token": refresh_token
    }

    headers = {"Content-Type": "application/json"}
    res = requests.post(url, json=payload, headers=headers).json()
    save_tokens(res)
    return jsonify(res)


# === STEP 4: Auto-refresh helper ===
@app.route("/auto_refresh")
def auto_refresh():
    data = load_tokens()
    if not data:
        return jsonify({"error": "No token data found."})
    if data.get("expire_in", 0) < 600:
        return refresh_token()
    return jsonify({"message": "Token still valid.", "data": data})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
