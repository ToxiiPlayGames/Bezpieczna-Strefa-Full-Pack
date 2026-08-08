BezpiecznaStrefa Premium Backend - SANDBOX

Render:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn --bind 0.0.0.0:$PORT app:app

Health Check Path:
/healthz

PIERWSZY DEPLOY:
Backend uruchomi sie bez danych PayPal. Render nada wtedy prawdziwy adres HTTPS.

POTEM w Render -> Environment dodaj:
PAYPAL_CLIENT_ID
PAYPAL_CLIENT_SECRET
PAYPAL_MODE=sandbox
PREMIUM_SERVER_KEY

Po utworzeniu prawidlowego webhooka PayPal dodaj:
PAYPAL_WEBHOOK_ID

Webhook URL:
https://TWOJ-PRAWDZIWY-ADRES.onrender.com/paypal/webhook

Event:
PAYMENT.CAPTURE.COMPLETED

Nie wklejaj Client Secret do GitHuba ani do czatu.
SQLite na darmowym Render jest tylko do Sandbox/testow. Przed LIVE trzeba podlaczyc trwala baze danych.
