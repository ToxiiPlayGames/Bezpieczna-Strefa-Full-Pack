import os
import sqlite3
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox").lower().strip()
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
PREMIUM_SERVER_KEY = os.getenv("PREMIUM_SERVER_KEY", "").strip()

PAYPAL_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE != "live" else "https://api-m.paypal.com"
DB_PATH = os.getenv("PREMIUM_DB_PATH", "/tmp/bezpiecznastrefa-premium.sqlite3")

PACKAGES = {
    "100": {"gems": 100, "price": "15.00", "currency": "PLN"},
    "250": {"gems": 250, "price": "35.00", "currency": "PLN"},
    "500": {"gems": 500, "price": "60.00", "currency": "PLN"},
    "1000": {"gems": 1000, "price": "100.00", "currency": "PLN"},
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capture_id TEXT UNIQUE NOT NULL,
            player_uuid TEXT NOT NULL,
            package_id TEXT NOT NULL,
            gems INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            claimed_at TEXT
        )
    """)
    conn.commit()
    return conn

def now():
    return datetime.now(timezone.utc).isoformat()

def auth_error():
    if not PREMIUM_SERVER_KEY:
        return jsonify({"error": "PREMIUM_SERVER_KEY is not configured"}), 503
    if request.headers.get("X-Server-Key", "") != PREMIUM_SERVER_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None

def paypal_token():
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise RuntimeError("PayPal credentials are not configured")
    r = requests.post(
        f"{PAYPAL_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def verify_webhook(event):
    if not PAYPAL_WEBHOOK_ID:
        return False
    token = paypal_token()
    payload = {
        "auth_algo": request.headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": request.headers.get("PAYPAL-CERT-URL"),
        "transmission_id": request.headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": request.headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": PAYPAL_WEBHOOK_ID,
        "webhook_event": event,
    }
    r = requests.post(
        f"{PAYPAL_BASE}/v1/notifications/verify-webhook-signature",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("verification_status") == "SUCCESS"

@app.get("/")
def home():
    return jsonify({"service": "BezpiecznaStrefa-Premium", "status": "online", "paypal_mode": PAYPAL_MODE})

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})

@app.get("/api/packages")
def packages():
    return jsonify(PACKAGES)

@app.post("/api/paypal/order")
def create_order():
    err = auth_error()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    player_uuid = str(body.get("minecraft_uuid", "")).strip()
    package_id = str(body.get("package_id", "")).strip()

    try:
        uuid.UUID(player_uuid)
    except Exception:
        return jsonify({"error": "invalid minecraft_uuid"}), 400

    package = PACKAGES.get(package_id)
    if not package:
        return jsonify({"error": "unknown package_id"}), 400

    custom_id = f"{player_uuid}|{package_id}|{uuid.uuid4().hex[:12]}"

    try:
        token = paypal_token()
        r = requests.post(
            f"{PAYPAL_BASE}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": uuid.uuid4().hex,
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "custom_id": custom_id,
                    "description": f"BezpiecznaStrefa - {package['gems']} Klejnotow",
                    "amount": {"currency_code": package["currency"], "value": package["price"]},
                }],
                "application_context": {
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                },
            },
            timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        return jsonify({"error": "paypal_error", "details": str(e)}), 502

    data = r.json()
    approve_url = next((x.get("href") for x in data.get("links", []) if x.get("rel") == "approve"), None)
    return jsonify({
        "order_id": data.get("id"),
        "approve_url": approve_url,
        "gems": package["gems"],
        "price": package["price"],
        "currency": package["currency"],
    }), 201

@app.post("/paypal/webhook")
def paypal_webhook():
    event = request.get_json(silent=True)
    if not isinstance(event, dict):
        return jsonify({"error": "invalid json"}), 400

    try:
        if not verify_webhook(event):
            return jsonify({"error": "unverified webhook"}), 400
    except Exception as e:
        return jsonify({"error": "webhook verification failed", "details": str(e)}), 502

    if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
        return jsonify({"ok": True, "ignored": event.get("event_type")})

    resource = event.get("resource") or {}
    capture_id = str(resource.get("id", "")).strip()
    custom_id = str(resource.get("custom_id", "")).strip()
    amount = resource.get("amount") or {}
    parts = custom_id.split("|")

    if len(parts) != 3:
        return jsonify({"error": "invalid custom_id"}), 400

    player_uuid, package_id, _ = parts
    package = PACKAGES.get(package_id)
    if not package:
        return jsonify({"error": "unknown package"}), 400

    if str(amount.get("currency_code", "")).upper() != package["currency"] or str(amount.get("value", "")) != package["price"]:
        return jsonify({"error": "amount mismatch"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO grants (capture_id, player_uuid, package_id, gems, created_at, claimed_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (capture_id, player_uuid, package_id, package["gems"], now()),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})

@app.get("/api/grants/<player_uuid>")
def grants(player_uuid):
    err = auth_error()
    if err:
        return err
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, capture_id, package_id, gems, created_at FROM grants WHERE player_uuid=? AND claimed_at IS NULL ORDER BY id",
            (player_uuid,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()

@app.post("/api/grants/<int:grant_id>/claim")
def claim(grant_id):
    err = auth_error()
    if err:
        return err
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE grants SET claimed_at=? WHERE id=? AND claimed_at IS NULL",
            (now(), grant_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "grant not found or already claimed"}), 404
        return jsonify({"ok": True})
    finally:
        conn.close()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
