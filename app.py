from flask import Flask, jsonify
import requests, hmac, hashlib, time, json, os, pandas as pd

app = Flask(__name__)

# === LIVE CREDENTIALS ===
PARTNER_ID = 2013146
PARTNER_KEY = "shpk62586365587979465a78544c795443456242756b64645076684258616459"
SHOP_ID = 706762797
HOST = "https://partner.shopeemobile.com"

# === FILE PATHS ===
TOKEN_FILE = "/mnt/data/tokens.json"
ORDER_FILE = "/mnt/data/sales.csv"
ITEM_FILE = "/mnt/data/sales_items.csv"
ESCROW_FILE = "/mnt/data/sales_gp.csv"

# === UTILITIES ===
def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_tokens(data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def sign(msg):
    return hmac.new(PARTNER_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()

TOKENS = load_tokens()

# === REFRESH TOKEN ===
def refresh_token():
    if not TOKENS.get("refresh_token"):
        return
    PATH = "/api/v2/auth/access_token/get"
    timestamp = int(time.time())
    base = f"{PARTNER_ID}{PATH}{timestamp}{TOKENS['refresh_token']}{SHOP_ID}"
    s = sign(base)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={s}"
    payload = {"partner_id": PARTNER_ID, "shop_id": SHOP_ID, "refresh_token": TOKENS["refresh_token"]}
    r = requests.post(url, json=payload)
    data = r.json()
    if "access_token" in data:
        TOKENS.update({
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "last_refresh": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        })
        save_tokens(TOKENS)
        print("✅ Token refreshed")
    else:
        print("⚠️ Refresh failed:", data)

# === FETCH ORDER LIST (SALES SUMMARY) ===
def fetch_orders(time_from=None):
    PATH = "/api/v2/shop/get_order_list"
    timestamp = int(time.time())
    base = f"{PARTNER_ID}{PATH}{timestamp}{TOKENS['access_token']}{SHOP_ID}"
    s = sign(base)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={s}&access_token={TOKENS['access_token']}&shop_id={SHOP_ID}"

    if not time_from:
        time_from = int(time.mktime(time.strptime("2020-01-01", "%Y-%m-%d")))
    time_to = int(time.time())

    all_orders, cursor = [], None
    while True:
        payload = {
            "time_range_field": "create_time",
            "time_from": time_from,
            "time_to": time_to,
            "page_size": 100
        }
        if cursor:
            payload["cursor"] = cursor
        res = requests.post(url, json=payload, timeout=30)
        data = res.json()
        if "response" not in data:
            break
        orders = data["response"].get("order_list", [])
        all_orders.extend(orders)
        if not data["response"].get("more"):
            break
        cursor = data["response"].get("next_cursor")
        time.sleep(0.5)
    return all_orders

@app.route("/update_sales")
def update_sales():
    refresh_token()
    orders = fetch_orders()
    if not orders:
        return jsonify({"message": "No orders found"})
    clean = []
    for o in orders:
        clean.append({
            "order_sn": o.get("order_sn"),
            "region": o.get("region"),
            "status": o.get("order_status"),
            "total_amount": o.get("total_amount", 0),
            "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(o.get("create_time", 0))),
            "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(o.get("update_time", 0)))
        })
    df = pd.DataFrame(clean)
    df.to_csv(ORDER_FILE, index=False)
    print(f"💾 Saved {len(df)} orders")
    return jsonify({"message": "✅ Orders saved", "count": len(df)})

# === FETCH ORDER DETAIL (ITEM LEVEL) ===
def fetch_order_detail(order_sn):
    PATH = "/api/v2/order/get_order_detail"
    timestamp = int(time.time())
    base = f"{PARTNER_ID}{PATH}{timestamp}{TOKENS['access_token']}{SHOP_ID}"
    s = sign(base)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={s}&access_token={TOKENS['access_token']}&shop_id={SHOP_ID}"
    payload = {"order_sn_list": [order_sn]}
    res = requests.post(url, json=payload, timeout=30)
    data = res.json()
    items = []
    for d in data.get("response", {}).get("order_list", []):
        for i in d.get("item_list", []):
            items.append({
                "order_sn": d.get("order_sn"),
                "item_id": i.get("item_id"),
                "sku": i.get("model_sku"),
                "name": i.get("item_name"),
                "qty": i.get("model_quantity_purchased"),
                "price": i.get("model_discounted_price"),
                "subtotal": i.get("model_discounted_price", 0) * i.get("model_quantity_purchased", 0),
                "status": d.get("order_status"),
                "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(d.get("create_time", 0)))
            })
    return items

@app.route("/update_sales_items")
def update_sales_items():
    if not os.path.exists(ORDER_FILE):
        return jsonify({"error": "No order list found. Run /update_sales first."})
    df_orders = pd.read_csv(ORDER_FILE)
    all_details = []
    for sn in df_orders["order_sn"].tolist():
        try:
            detail = fetch_order_detail(sn)
            all_details.extend(detail)
        except Exception as e:
            print("⚠️ Error fetching details:", e)
        time.sleep(0.5)
    if not all_details:
        return jsonify({"error": "No item details fetched"})
    df = pd.DataFrame(all_details)
    df.to_csv(ITEM_FILE, index=False)
    print(f"💾 Saved {len(df)} sales item rows")
    return jsonify({"message": "✅ Item details saved", "count": len(df)})

# === ESCROW (FEE / COMMISSION / GP) ===
def fetch_escrow(order_sn):
    PATH = "/api/v2/payment/get_escrow_detail"
    timestamp = int(time.time())
    base = f"{PARTNER_ID}{PATH}{timestamp}{TOKENS['access_token']}{SHOP_ID}"
    s = sign(base)
    url = f"{HOST}{PATH}?partner_id={PARTNER_ID}&timestamp={timestamp}&sign={s}&access_token={TOKENS['access_token']}&shop_id={SHOP_ID}"
    payload = {"order_sn": order_sn}
    r = requests.post(url, json=payload, timeout=30)
    d = r.json()
    if "response" not in d:
        return None
    e = d["response"]
    return {
        "order_sn": order_sn,
        "total_amount": e.get("order_income_detail", {}).get("buyer_payment_amount", 0),
        "service_fee": e.get("order_income_detail", {}).get("service_fee", 0),
        "commission_fee": e.get("order_income_detail", {}).get("commission_fee", 0),
        "escrow_amount": e.get("order_income_detail", {}).get("escrow_amount", 0)
    }

@app.route("/update_sales_gp")
def update_sales_gp():
    if not os.path.exists(ORDER_FILE):
        return jsonify({"error": "No order list found."})
    df_orders = pd.read_csv(ORDER_FILE)
    all_gp = []
    for sn in df_orders["order_sn"].tolist():
        try:
            gp = fetch_escrow(sn)
            if gp:
                all_gp.append(gp)
        except Exception as e:
            print("⚠️ Error:", e)
        time.sleep(0.5)
    if not all_gp:
        return jsonify({"error": "No GP data fetched"})
    df = pd.DataFrame(all_gp)
    df.to_csv(ESCROW_FILE, index=False)
    print(f"💾 Saved {len(df)} GP rows")
    return jsonify({"message": "✅ GP data saved", "count": len(df)})

# === READ ENDPOINTS (for Power BI) ===
@app.route("/sales_data")
def sales_data():
    if not os.path.exists(ORDER_FILE):
        return jsonify({"error": "No sales data"})
    df = pd.read_csv(ORDER_FILE)
    return jsonify(df.to_dict(orient="records"))

@app.route("/sales_items")
def sales_items():
    if not os.path.exists(ITEM_FILE):
        return jsonify({"error": "No item data"})
    df = pd.read_csv(ITEM_FILE)
    return jsonify(df.to_dict(orient="records"))

@app.route("/sales_gp")
def sales_gp():
    if not os.path.exists(ESCROW_FILE):
        return jsonify({"error": "No GP data"})
    df = pd.read_csv(ESCROW_FILE)
    return jsonify(df.to_dict(orient="records"))

@app.route("/")
def home():
    return jsonify({
        "status": "✅ Shopee Flask Server Running OK (Live Mode)",
        "shop_id": TOKENS.get("shop_id"),
        "last_refresh": TOKENS.get("last_refresh")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
