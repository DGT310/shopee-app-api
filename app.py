from flask import Flask, request, redirect, jsonify
import time, hmac, hashlib, requests, os, json

# === Force UTC timezone ===
os.environ["TZ"] = "UTC"
try:
    time.tzset()
except AttributeError:
    # Windows / some Render environments don’t support tzset()
    pass

app = Flask(__name__)

# === CONFIGURATION (LIVE MODE) ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
SHOP_ID = 706762797
HOST = "https://partner.shopeemobile.com"  # ✅ LIVE endpoint
REDIRECT_URL = "https://shopee-app-api.onrender.com/callback"
TOKEN_FILE = "tokens.json"


# === Utility: Save / Load token ===
def save_tokens(data):
    """Save Shopee access and refresh tokens."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_tokens():
    """Load stored tokens from file if available."""
    if not os.path.exists(TOKEN_FILE):
        return {}
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


# === Utility: Generate valid 32-bit timestamp (Shopee requirement) ===
def get_shopee_timestamp():
    """
    Shopee requires timestamps as a 32-bit integer (seconds, not ms).
    Add optional offset via TIME_OFFSET environment variable if needed.
    """
    offset = int(os.getenv("TIME_OFFSET", "0"))
    ts = (int(time.time()) + offset) % 4294967295  # ✅ Safe 32-bit integer
    print(f"🕒 Using UTC timestamp: {ts} (offset {offset}s)")
    return ts


@app.route("/")
def home():
    return "✅ Shopee Flask API Server Running (LIVE Mode, UTC-safe timestamp)"


# === STEP 1: Authorize shop ===
@app.route("/authorize")
def authorize():
    """Redirect user to Shopee authorization page."""
    path = "/api/v2/shop/auth_partner"
    timestamp = get_shopee_timestamp()

    base_string = f"{PARTNER_ID}{path}{timestamp}"
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    url = (
        f"{HOST}{path}"
        f"?partner_id={PARTNER_ID}"
        f"&timestamp={timestamp}"
        f"&sign={sign}"
        f"&redirect={REDIRECT_URL}"
    )

    print(f"🔗 Authorization URL: {url}")
    return redirect(url)


# === STEP 2: Handle callback and exchange code for token ===
@app.route("/callback")
def callback():
    """Handle Shopee redirect and exchange code for access token."""
    raw_query = request.query_string.decode("utf-8")
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return jsonify({
            "error": "Missing code or shop_id",
            "raw_query": raw_query
        })

    path = "/api/v2/auth/token/get"
    timestamp = get_shopee_timestamp()
    base_string = f"{PARTNER_ID}{path}{timestamp}{code}"
    sign = hmac.new(
        PARTNER_KEY.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    url = f"{HOST}{path}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={sign}"

    payload = {
        "code": code,              # must be raw (not decoded)
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }
    headers = {"Content-Type": "application/json"}

    print("📤 Token Request:", url, payload)
    res = requests.post(url, json=payload, headers=headers).json()

    save_tokens(res)

    return jsonify({
        "used_code": code,
        "debug_base_string": base_string,
        "debug_sign": sign,
        "api_response": res,
        "raw_query": raw_query
    })


# === STEP 3: Refresh access token ===
@app.route("/refresh_token")
def refresh_token():
    """Use the refresh token to get a new access token."""
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
    print("🔁 Refresh Request:", url)
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

    if data.get("expire_in", 0) < 600:  # 10 min before expiry
        return refresh_token()

    return jsonify({
        "message": "Token still valid.",
        "data": data
    })


# === Diagnostic: See current UTC time and offset ===
@app.route("/check_time")
def check_time():
    """Compare UTC time and current offset."""
    return jsonify({
        "utc_time": int(time.time()),
        "offset_used": int(os.getenv("TIME_OFFSET", "0"))
    })


# === Run Flask app ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
