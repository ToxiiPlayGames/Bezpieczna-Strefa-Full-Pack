import os
import sqlite3
import uuid
from datetime import datetime, timezone
from html import escape

import requests
from flask import Flask, jsonify, redirect, request

app = Flask(__name__)

PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox").lower().strip()
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
PREMIUM_SERVER_KEY = os.getenv("PREMIUM_SERVER_KEY", "").strip()

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://bezpieczna-strefa-full-pack.onrender.com"
).rstrip("/")

PAYPAL_BASE = (
    "https://api-m.sandbox.paypal.com"
    if PAYPAL_MODE != "live"
    else "https://api-m.paypal.com"
)

DB_PATH = os.getenv(
    "PREMIUM_DB_PATH",
    "/tmp/bezpiecznastrefa-premium.sqlite3"
)

PACKAGES = {
    "100":  {"gems": 100,  "price": "15.00",  "currency": "PLN"},
    "250":  {"gems": 250,  "price": "35.00",  "currency": "PLN"},
    "500":  {"gems": 500,  "price": "60.00",  "currency": "PLN"},
    "1000": {"gems": 1000, "price": "100.00", "currency": "PLN"},
}

TEST_UUID = "00000000-0000-0000-0000-000000000001"


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


def paypal_token():
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise RuntimeError("PayPal credentials are not configured")

    r = requests.post(
        f"{PAYPAL_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def require_server_key():
    if not PREMIUM_SERVER_KEY:
        return jsonify({"error": "PREMIUM_SERVER_KEY is not configured"}), 503
    supplied = request.headers.get("X-Server-Key", "")
    if supplied != PREMIUM_SERVER_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None


def create_paypal_order(player_uuid: str, package_id: str):
    try:
        uuid.UUID(player_uuid)
    except Exception:
        raise ValueError("invalid minecraft_uuid")

    package = PACKAGES.get(package_id)
    if not package:
        raise ValueError("unknown package_id")

    token = paypal_token()
    custom_id = f"{player_uuid}|{package_id}|{uuid.uuid4().hex[:12]}"

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "custom_id": custom_id,
            "description": f"BezpiecznaStrefa - {package['gems']} Klejnotow",
            "amount": {
                "currency_code": package["currency"],
                "value": package["price"],
            },
        }],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "brand_name": "BezpiecznaStrefa",
                    "shipping_preference": "NO_SHIPPING",
                    "user_action": "PAY_NOW",
                    "return_url": f"{PUBLIC_BASE_URL}/paypal/return",
                    "cancel_url": f"{PUBLIC_BASE_URL}/paypal/cancel",
                }
            }
        },
    }

    r = requests.post(
        f"{PAYPAL_BASE}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": uuid.uuid4().hex,
            "Prefer": "return=representation",
        },
        json=payload,
        timeout=20,
    )
    r.raise_for_status()

    data = r.json()
    approve_url = next(
        (
            link.get("href")
            for link in data.get("links", [])
            if link.get("rel") in ("payer-action", "approve")
        ),
        None,
    )

    return {
        "order_id": data.get("id"),
        "approve_url": approve_url,
        "package": package,
    }


def insert_grant_from_capture(capture: dict):
    capture_id = str(capture.get("id", "")).strip()
    custom_id = str(capture.get("custom_id", "")).strip()
    amount = capture.get("amount") or {}

    parts = custom_id.split("|")
    if len(parts) != 3:
        raise ValueError("invalid custom_id")

    player_uuid, package_id, _nonce = parts
    package = PACKAGES.get(package_id)
    if not package:
        raise ValueError("unknown package")

    try:
        uuid.UUID(player_uuid)
    except Exception:
        raise ValueError("invalid player uuid")

    currency = str(amount.get("currency_code", "")).upper()
    value = str(amount.get("value", ""))

    if currency != package["currency"] or value != package["price"]:
        raise ValueError("amount mismatch")

    if not capture_id:
        raise ValueError("missing capture id")

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO grants
            (capture_id, player_uuid, package_id, gems, created_at, claimed_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (
                capture_id,
                player_uuid,
                package_id,
                package["gems"],
                now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "capture_id": capture_id,
        "player_uuid": player_uuid,
        "package_id": package_id,
        "gems": package["gems"],
    }


def extract_completed_capture(order: dict):
    for unit in order.get("purchase_units", []):
        payments = unit.get("payments") or {}
        for capture in payments.get("captures", []):
            if capture.get("status") == "COMPLETED":
                if not capture.get("custom_id") and unit.get("custom_id"):
                    capture = dict(capture)
                    capture["custom_id"] = unit["custom_id"]
                return capture
    return None


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
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("verification_status") == "SUCCESS"


@app.get("/")
def home():
    return jsonify({
        "service": "BezpiecznaStrefa-Premium",
        "status": "online",
        "paypal_mode": PAYPAL_MODE,
        "test_page": f"{PUBLIC_BASE_URL}/sandbox-test"
            if PAYPAL_MODE == "sandbox" else None,
    })


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/api/packages")
def packages():
    return jsonify(PACKAGES)


@app.post("/api/paypal/order")
def api_create_order():
    err = require_server_key()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    player_uuid = str(body.get("minecraft_uuid", "")).strip()
    package_id = str(body.get("package_id", "")).strip()

    try:
        result = create_paypal_order(player_uuid, package_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "paypal_error", "details": str(e)}), 502

    return jsonify(result), 201


@app.get("/sandbox-test")
def sandbox_test():
    if PAYPAL_MODE != "sandbox":
        return "Sandbox test disabled in LIVE mode.", 404

    buttons = []
    for package_id, package in PACKAGES.items():
        buttons.append(
            f"""
            <form method="post" action="/sandbox-test/order">
                <input type="hidden" name="package_id" value="{escape(package_id)}">
                <button type="submit">
                    {package['gems']} Klejnotow - {package['price']} PLN
                </button>
            </form>
            """
        )

    return f"""
    <!doctype html>
    <html lang="pl">
    <head>
        <meta charset="utf-8">
        <title>BezpiecznaStrefa Premium - Sandbox</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 680px; margin: 60px auto; padding: 20px; }}
            button {{ width: 100%; padding: 16px; margin: 8px 0; font-size: 18px; cursor: pointer; }}
            .warn {{ padding: 12px; background: #eee; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <h1>BezpiecznaStrefa Premium - TEST SANDBOX</h1>
        <div class="warn">To NIE pobiera prawdziwych pieniedzy. Uzyj konta PayPal Sandbox Buyer.</div>
        {''.join(buttons)}
    </body>
    </html>
    """


@app.post("/sandbox-test/order")
def sandbox_test_order():
    if PAYPAL_MODE != "sandbox":
        return "Sandbox test disabled in LIVE mode.", 404

    package_id = str(request.form.get("package_id", "")).strip()

    try:
        result = create_paypal_order(TEST_UUID, package_id)
    except Exception as e:
        return f"Blad tworzenia zamowienia PayPal: {escape(str(e))}", 502

    if not result.get("approve_url"):
        return "PayPal nie zwrocil linku zatwierdzenia.", 502

    return redirect(result["approve_url"], code=302)


@app.get("/paypal/return")
def paypal_return():
    order_id = str(request.args.get("token", "")).strip()
    if not order_id:
        return "Brak tokenu zamowienia PayPal.", 400

    try:
        token = paypal_token()
        r = requests.post(
            f"{PAYPAL_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "PayPal-Request-Id": f"capture-{order_id}",
                "Prefer": "return=representation",
            },
            json={},
            timeout=20,
        )
        r.raise_for_status()
        order = r.json()

        capture = extract_completed_capture(order)
        if not capture:
            return "Platnosc nie ma statusu COMPLETED.", 409

        grant = insert_grant_from_capture(capture)

    except Exception as e:
        return f"Blad finalizacji platnosci: {escape(str(e))}", 502

    return f"""
    <!doctype html>
    <html lang="pl">
    <head><meta charset="utf-8"><title>Platnosc zakonczona</title></head>
    <body style="font-family:Arial,sans-serif;max-width:680px;margin:60px auto;padding:20px">
        <h1>Platnosc Sandbox zakonczona</h1>
        <p>Przyznano testowo: <strong>{grant['gems']} Klejnotow</strong>.</p>
        <p>Capture ID: {escape(grant['capture_id'])}</p>
        <p>To nadal jest Sandbox - bez prawdziwych pieniedzy.</p>
    </body>
    </html>
    """


@app.get("/paypal/cancel")
def paypal_cancel():
    return """
    <!doctype html>
    <html lang="pl">
    <head><meta charset="utf-8"><title>Anulowano</title></head>
    <body style="font-family:Arial,sans-serif;max-width:680px;margin:60px auto;padding:20px">
        <h1>Platnosc anulowana</h1>
        <p>Nie pobrano srodkow i nie przyznano Klejnotow.</p>
    </body>
    </html>
    """


@app.post("/paypal/webhook")
def paypal_webhook():
    event = request.get_json(silent=True)
    if not isinstance(event, dict):
        return jsonify({"error": "invalid json"}), 400

    try:
        if not verify_webhook(event):
            return jsonify({"error": "unverified webhook"}), 400
    except Exception as e:
        return jsonify({
            "error": "webhook verification failed",
            "details": str(e),
        }), 502

    if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
        return jsonify({
            "ok": True,
            "ignored": event.get("event_type"),
        })

    resource = event.get("resource") or {}

    try:
        grant = insert_grant_from_capture(resource)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"ok": True, "grant": grant})


@app.get("/api/grants/<player_uuid>")
def grants(player_uuid):
    err = require_server_key()
    if err:
        return err

    try:
        uuid.UUID(player_uuid)
    except Exception:
        return jsonify({"error": "invalid player uuid"}), 400

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, capture_id, package_id, gems, created_at
            FROM grants
            WHERE player_uuid = ? AND claimed_at IS NULL
            ORDER BY id
            """,
            (player_uuid,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.post("/api/grants/<int:grant_id>/claim")
def claim(grant_id):
    err = require_server_key()
    if err:
        return err

    conn = get_db()
    try:
        cur = conn.execute(
            """
            UPDATE grants
            SET claimed_at = ?
            WHERE id = ? AND claimed_at IS NULL
            """,
            (now(), grant_id),
        )
        conn.commit()

        if cur.rowcount == 0:
            return jsonify({
                "error": "grant not found or already claimed",
            }), 404

        return jsonify({"ok": True})
    finally:
        conn.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
