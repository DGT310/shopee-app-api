from flask import Flask, request, redirect, jsonify
import time, hmac, hashlib, requests, os, json, binascii

app = Flask(__name__)

# === CONFIGURATION ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
SHOP_ID = 706762797
HOST = "https://partner.shopeemobile.com"

# ✅ Must match your Shopee “Live Redirect URL Domain”
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


# === Utility: Get Shopee server time (Hybrid Method) ===
def get_shopee_timestamp():
    """
    Try live Shopee time first; fallback to test-stable if needed.
    Add small +2s offset for network latency tolerance.
    """
    local_ts = int(time.time())
    try:
        # Try LIVE environment first
        res = requests.get("https://partner.shopeemobile.com/api/v2/public/get_shopee_time", timeout=5).json()
        if "timestamp" in res:
            shopee_ts = int(res["timestamp"])
            print(f"✅ Using LIVE Shopee time: {shopee_ts}")
            return shopee_ts

        print("⚠️ Live Shopee time returned error:", res)

        # Try TEST-STABLE fallback
        res = requests.get("https://partner.test-stable.shopeemobile.com/api/v2/public/get_shopee_time", timeout=5).json()
        if "timestamp" in res:
            shopee_ts = int(res["timestamp"])
            print(f"✅ Using TEST-STABLE Shopee time: {shopee_ts}")
            return shopee_ts + 2  # small offset for latency

    except Exception as e:
        print("⚠️ Cannot fetch Shopee time:", e)

    print(f"⚠️ Using local system time: {local_ts}")
    return local_ts + 2  # final fallback with offset


@app.route("/")
def home():
    return "✅ Shopee Flask API Server Running"


# === STEP 1: Authorize shop ===
@app.route("/authorize")
def authorize():
    path = "/api/v2/shop/auth_partner"
    timestamp = get_shopee_timestamp()

    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}&redirect={REDIRECT_URL}"
    print("🔗 Authorization URL:", url)
    return redirect(url)


# === STEP 2: Callback from Shopee ===
@app.route("/callback")
def callback():
    raw_query = request.query_string.decode("utf-8")
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return jsonify({"error": "Missing code or shop_id", "raw_query": raw_query})

    # ✅ Decode hex code if Shopee encoded it
    try:
        if all(c in "0123456789abcdefABCDEF" for c in code):
            decoded_code = binascii.unhexlify(code).decode("utf-8")
            code = decoded_code
    except Exception:
        pass

    # Wait a bit for Shopee to process the auth code
    time.sleep(2)

    path = "/api/v2/auth/token/get"
    timestamp = get_shopee_timestamp()

    # ✅ shop_id is NOT part of base string
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}"
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

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
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
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
    """Automatically refresh token if close to expiry."""
    data = load_tokens()
    if not data:
        return jsonify({"error": "No token data found."})

    expire_time = data.get("expire_in", 0)
    if expire_time < 600:  # less than 10 minutes remaining
        return refresh_token()
    return jsonify({"message": "Token still valid.", "data": data})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
