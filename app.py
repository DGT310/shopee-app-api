import os
import json
import time
import hmac
import hashlib
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================
PARTNER_ID = int(os.getenv("PARTNER_ID", "2013146"))
PARTNER_KEY = os.getenv("PARTNER_KEY", "shpk62586365587979465a78544c795443456242756b64645076684258616459")
HOST = "https://partner.shopeemobile.com"

TOKEN_FILE = "/mnt/data/tokens.json"

# ============================================================
# TOKEN UTILITIES
# ============================================================
def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_tokens():
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(TOKENS, f, indent=2)

def sign_msg(msg: str) -> str:
    return hmac.new(
        PARTNER_KEY.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

TOKENS = load_tokens()

def update_tokens_from_response(data: dict, shop_id: int):
    now = int(time.time())
    TOKENS["shop_id"] = int(shop_id)
    TOKENS["access_token"] = data["access_token"]
    TOKENS["refresh_token"] = data["refresh_token"]

    access_life = data.get("expire_in") or data.get("expires_in") or 4 * 3600
    refresh_life = data.get("refresh_token_expire_in") or 30 * 24 * 3600

    TOKENS["access_expire_at"] = now + int(access_life)
    TOKENS["refresh_expire_at"] = now + int(refresh_life)
    TOKENS["last_refresh"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))

    save_tokens()

def refresh_access_token():
    """Refresh the access token using refresh_token."""
    if not TOKENS.get("refresh_token") or not TOKENS.get("shop_id"):
        raise RuntimeError("❌ No refresh_token or shop_id stored. Re-authorize via /callback")

    PATH = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    base = f"{PARTNER_ID}{PATH}{ts}"
    sign = sign_msg(base)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={ts}&sign={sign}"
    payload = {
        "partner_id": PARTNER_ID,
        "shop_id": int(TOKENS["shop_id"]),
        "refresh_token": TOKENS["refresh_token"]
    }

    r = requests.post(url, json=payload, timeout=20)
    data = r.json()

    if "access_token" not in data:
        raise RuntimeError(f"❌ Refresh failed: {data}")

    update_tokens_from_response(data, int(TOKENS["shop_id"]))
    print("✅ Access token refreshed successfully")

def ensure_access_token() -> str:
    """Ensure the access_token is valid; refresh if expiring."""
    now = int(time.time())

    if not TOKENS.get("access_token") or not TOKENS.get("shop_id"):
        raise RuntimeError("❌ No access_token/shop_id. Run authorization first via /callback")

    if now > TOKENS.get("access_expire_at", 0) - 60:
        refresh_access_token()

    return TOKENS["access_token"]

def signed_shop_url(path: str) -> str:
    """Build signed URL for all shop-level APIs."""
    ts = int(time.time())
    access_token = ensure_access_token()
    shop_id = TOKENS["shop_id"]

    base = f"{PARTNER_ID}{path}{ts}{access_token}{shop_id}"
    sign = sign_msg(base)

    return (
        f"{HOST}{path}"
        f"?partner_id={PARTNER_ID}"
        f"&timestamp={ts}"
        f"&sign={sign}"
        f"&access_token={access_token}"
        f"&shop_id={shop_id}"
    )

def parse_date_to_unix(d: str) -> int:
    dt = datetime.strptime(d, "%Y-%m-%d")
    return int(dt.timestamp())

# ============================================================
# HEALTH CHECK
# ============================================================
@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "shop_id": TOKENS.get("shop_id"),
        "has_tokens": bool(TOKENS.get("access_token")),
        "last_refresh": TOKENS.get("last_refresh")
    })

@app.route("/ping")
def ping():
    return "pong", 200

# ============================================================
# 1️⃣ AUTH CALLBACK – RUN THIS ONCE
# ============================================================
@app.route("/callback")
def callback():
    code = request.args.get("code")
    shop_id = request.args.get("shop_id")

    if not code or not shop_id:
        return "❌ Missing code or shop_id", 400

    PATH = "/api/v2/auth/token/get"
    ts = int(time.time())
    base = f"{PARTNER_ID}{PATH}{ts}"
    sign = sign_msg(base)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={ts}&sign={sign}"
    payload = {
        "code": code,
        "shop_id": int(shop_id),
        "partner_id": PARTNER_ID
    }

    r = requests.post(url, json=payload, timeout=20)
    data = r.json()

    if "access_token" not in data:
        return jsonify({"error": data}), 400

    update_tokens_from_response(data, int(shop_id))

    return jsonify({
        "message": "✅ Shopee token exchange success",
        "shop_id": shop_id,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"]
    })

# ============================================================
# SHARED ORDER LIST FETCHER
# ============================================================
def get_orders_for_range(time_from: int, time_to: int):
    PATH = "/api/v2/order/get_order_list"
    url = signed_shop_url(PATH)

    all_orders = []
    cursor = None

    while True:
        payload = {
            "time_range_field": "create_time",
            "time_from": time_from,
            "time_to": time_to,
            "page_size": 100
        }
        if cursor:
            payload["cursor"] = cursor

        r = requests.post(url, json=payload, timeout=30)
        data = r.json()

        if "response" not in data:
            raise RuntimeError(f"Shopee get_order_list returned unexpected response: {data}")

        resp = data["response"]
        all_orders.extend(resp.get("order_list", []))

        if not resp.get("more"):
            break

        cursor = resp.get("next_cursor")
        time.sleep(0.2)

    return all_orders

# ============================================================
# 2️⃣ ORDERS (HEADER)
# ============================================================
@app.route("/orders")
def orders():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if not date_from or not date_to:
        return jsonify({"error": "Missing date_from or date_to"}), 400

    try:
        time_from = parse_date_to_unix(date_from)
        time_to = parse_date_to_unix(date_to) + 86400 - 1

        orders = get_orders_for_range(time_from, time_to)
        return jsonify(orders)
    except Exception as e:
        # This will turn the internal error into a readable JSON
        return jsonify({
            "error": "server_exception",
            "detail": str(e)
        }), 500
# ============================================================
# 3️⃣ ORDER DETAILS (ITEM LIST + FULL DETAIL)
# ============================================================
def get_order_details_for_sns(order_sns):
    PATH = "/api/v2/order/get_order_detail"
    url = signed_shop_url(PATH)

    all_details = []
    batch_size = 50

    for i in range(0, len(order_sns), batch_size):
        batch = order_sns[i:i+batch_size]
        payload = {"order_sn_list": batch}

        r = requests.post(url, json=payload, timeout=30)
        data = r.json()

        if "response" in data:
            all_details.extend(data["response"].get("order_list", []))

        time.sleep(0.2)

    return all_details

@app.route("/order_details")
def order_details():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    time_from = parse_date_to_unix(date_from)
    time_to = parse_date_to_unix(date_to) + 86400 - 1

    orders = get_orders_for_range(time_from, time_to)
    order_sns = [o["order_sn"] for o in orders]

    if not order_sns:
        return jsonify([])

    details = get_order_details_for_sns(order_sns)
    return jsonify(details)

# ============================================================
# 4️⃣ ESCROW (FEES / INCOME)
# ============================================================
def get_escrow_for_sns(order_sns):
    PATH = "/api/v2/payment/get_escrow_detail"
    url = signed_shop_url(PATH)

    results = []

    for sn in order_sns:
        payload = {"order_sn": sn}
        r = requests.post(url, json=payload, timeout=30)
        data = r.json()

        if "response" in data:
            escrow = {"order_sn": sn}
            escrow.update(data["response"])
            results.append(escrow)

        time.sleep(0.2)

    return results

@app.route("/escrow")
def escrow():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    time_from = parse_date_to_unix(date_from)
    time_to = parse_date_to_unix(date_to) + 86400 - 1

    orders = get_orders_for_range(time_from, time_to)
    order_sns = [o["order_sn"] for o in orders]

    if not order_sns:
        return jsonify([])

    escrow_data = get_escrow_for_sns(order_sns)
    return jsonify(escrow_data)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

