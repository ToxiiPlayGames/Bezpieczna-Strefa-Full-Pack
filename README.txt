BezpiecznaStrefa Premium Backend - Neon PostgreSQL

W Render -> Environment dodaj:
DATABASE_URL=<pelny Connection string skopiowany z Neon>

NIE wysylaj DATABASE_URL na czacie i NIE wrzucaj go do GitHuba.
Zawiera haslo do bazy.

Pozostale zmienne Render zostaja:
PAYPAL_CLIENT_ID
PAYPAL_CLIENT_SECRET
PAYPAL_MODE
PAYPAL_WEBHOOK_ID
PREMIUM_SERVER_KEY

Po podmianie app.py i requirements.txt Render zrobi auto-deploy.
Health check:
https://bezpieczna-strefa-full-pack.onrender.com/healthz

Poprawny wynik:
{"ok":true,"database":"neon-postgres"}
