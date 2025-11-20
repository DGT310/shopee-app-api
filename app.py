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
PARTNER_KEY = os.getenv(
    "PARTNER_KEY",
    "shpk62586365587979465a78544c795443456242756b64645076684258616459",
)
HOST = "https://partner.shopeemobile.com"   # Production Shopee partner API


# ============================================================
# TOKEN UTILITIES (ENV-based for Render FREE tier)
# ============================================================

def load_tokens():
    """
    On Render FREE plan, file storage is erased.
    → So we load initial tokens from ENV only.
    """
    tokens = {}
    shop_id = os.getenv("SHOPEE_SHOP_ID")
    refresh_token = os.getenv("SHOPEE_REFRESH_TOKEN")

    if shop_id:
        tokens["shop_id"] = int(shop_id)
    if refresh_token:
        tokens["refresh_token"] = refresh_token
    return tokens


def save_tokens():
    """No file storage; just print so user can update ENV manually."""
    print("Current tokens:", {
        "shop_id": TOKENS.get("shop_id"),
        "access_token": TOKENS.get("access_token"),
        "refresh_token": TOKENS.get("refresh_token"),
        "access_expire_at": TOKENS.get("access_expire_at"),
        "refresh_expire_at": TOKENS.get("refresh_expire_at"),
    })


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
    if not TOKENS.get("refresh_token") or not TOKENS.get("shop_id"):
        raise RuntimeError(
            "❌ Missing refresh_token/shop_id. "
            "Authorize via /callback OR set ENV vars."
        )

    PATH = "/api/v2/auth/access_token/get"
    ts = int(time.time())
    base = f"{PARTNER_ID}{PATH}{ts}"
    sign = sign_msg(base)

    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={ts}&sign={sign}"
    payload = {
        "partner_id": PARTNER_ID,
        "shop_id": TOKENS["shop_id"],
        "refresh_token": TOKENS["refresh_token"],
    }

    r = requests.post(url, json=payload, timeout=20)
    data = r.json()

    if "access_token" not in data:
        raise RuntimeError(f"❌ Failed to refresh access_token: {data}")

    update_tokens_from_response(data, TOKENS["shop_id"])
    print("✅ Token refreshed")


def ensure_access_token() -> str:
    now = int(time.time())

    if not TOKENS.get("shop_id"):
        raise RuntimeError("❌ No shop_id set. Authorize via /callback.")

    if not TOKENS.get("access_token"):
        refresh_access_token()
        return TOKENS["access_token"]

    if now > TOKENS.get("access_expire_at", 0) - 60:
        refresh_access_token()

    return TOKENS["access_token"]


def signed_shop_url(path: str) -> str:
    ts = int(time.time())
    access_token = ensure_access_token()
    shop_id = TOKENS["shop_id"]

    base = f"{PARTNER_ID}{path}{ts}{access_token}{shop_id}"
    s = sign_msg(base)

    return (
        f"{HOST}{path}"
        f"?partner_id={PARTNER_ID}"
        f"&timestamp={ts}"
        f"&sign={s}"
        f"&access_token={access_token}"
        f"&shop_id={shop_id}"
    )


# ============================================================
# SHOPEE SAFE JSON PARSER (Used by ALL API calls)
# ============================================================

def safe_json_request(req, endpoint_name):
    try:
        data = req.json()
    except Exception as je:
        raise RuntimeError(
            f"{endpoint_name} invalid JSON "
            f"(status={req.status_code}, url={req.url}): {req.text}"
        ) from je

    if "response" not in data:
        raise RuntimeError(
            f"{endpoint_name} unexpected structure "
            f"(status={req.status_code}, url={req.url}): {data}"
        )

    return data


# ============================================================
# HEALTH / STATUS ENDPOINTS
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "shop_id": TOKENS.get("shop_id"),
        "has_tokens": bool(TOKENS.get("access_token")),
        "has_refresh_token": bool(TOKENS.get("refresh_token")),
        "last_refresh": TOKENS.get("last_refresh"),
    })


@app.route("/status")
def status():
    return jsonify(TOKENS)


# ============================================================
# AUTH CALLBACK
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
    payload = {"code": code, "shop_id": int(shop_id), "partner_id": PARTNER_ID}

    r = requests.post(url, json=payload, timeout=20)
    data = r.json()

    if "access_token" not in data:
        return jsonify({"error": data}), 400

    update_tokens_from_response(data, int(shop_id))

    return jsonify({
        "message": "✅ Token exchange success",
        "shop_id": shop_id,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "note": "👉 Save these into Render ENV for persistence."
    })


# ============================================================
# FETCH ORDERS LIST
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
            "page_size": 100,
        }
        if cursor:
            payload["cursor"] = cursor

        r = requests.get(url, params=payload, timeout=30)
        data = safe_json_request(r, "get_order_list")

        resp = data["response"]
        all_orders.extend(resp.get("order_list", []))

        if not resp.get("more"):
            break

        cursor = resp.get("next_cursor")
        time.sleep(0.2)

    return all_orders


@app.route("/orders")
def orders():
    try:
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        if not date_from or not date_to:
            return jsonify({"error": "Missing date range"}), 400

        t1 = int(datetime.strptime(date_from, "%Y-%m-%d").timestamp())
        t2 = int(datetime.strptime(date_to, "%Y-%m-%d").timestamp()) + 86399

        return jsonify(get_orders_for_range(t1, t2))

    except Exception as e:
        import traceback
        return jsonify({
            "error": "server_exception",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# FETCH ORDER DETAILS
# ============================================================

def get_order_details_for_sns(order_sns):
    PATH = "/api/v2/order/get_order_detail"
    url = signed_shop_url(PATH)

    results = []
    batch_size = 50

    for i in range(0, len(order_sns), batch_size):
        payload = {"order_sn_list": order_sns[i:i+batch_size]}
        r = requests.post(url, json=payload, timeout=30)
        data = safe_json_request(r, "get_order_detail")

        results.extend(data["response"].get("order_list", []))
        time.sleep(0.2)

    return results


@app.route("/order_details")
def order_details():
    try:
        d1 = request.args.get("date_from")
        d2 = request.args.get("date_to")

        if not d1 or not d2:
            return jsonify({"error": "Missing date range"}), 400

        t1 = int(datetime.strptime(d1, "%Y-%m-%d").timestamp())
        t2 = int(datetime.strptime(d2, "%Y-%m-%d").timestamp()) + 86399

        orders = get_orders_for_range(t1, t2)
        if not orders:
            return jsonify([])

        sns = [o["order_sn"] for o in orders]
        return jsonify(get_order_details_for_sns(sns))

    except Exception as e:
        import traceback
        return jsonify({
            "error": "server_exception",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# FETCH ESCROW
# ============================================================

def get_escrow_for_sns(order_sns):
    PATH = "/api/v2/payment/get_escrow_detail"
    url = signed_shop_url(PATH)

    results = []

    for sn in order_sns:
        r = requests.post(url, json={"order_sn": sn}, timeout=20)
        data = safe_json_request(r, "get_escrow_detail")

        row = {"order_sn": sn}
        row.update(data["response"])
        results.append(row)
        time.sleep(0.2)

    return results


@app.route("/escrow")
def escrow():
    try:
        d1 = request.args.get("date_from")
        d2 = request.args.get("date_to")

        if not d1 or not d2:
            return jsonify({"error": "Missing date range"}), 400

        t1 = int(datetime.strptime(d1, "%Y-%m-%d").timestamp())
        t2 = int(datetime.strptime(d2, "%Y-%m-%d").timestamp()) + 86399

        orders = get_orders_for_range(t1, t2)
        sns = [o["order_sn"] for o in orders]

        if not sns:
            return jsonify([])

        return jsonify(get_escrow_for_sns(sns))

    except Exception as e:
        import traceback
        return jsonify({
            "error": "server_exception",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
