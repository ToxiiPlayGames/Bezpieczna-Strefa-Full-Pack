BezpiecznaStrefa Premium Backend v2 - SANDBOX

CO POPRAWIONO:
- PayPal ma return_url i cancel_url.
- Po zatwierdzeniu Sandbox backend wywoluje Orders API /capture.
- PAYMENT.CAPTURE.COMPLETED nadal jest weryfikowany przez webhook.
- Przyznanie jest idempotentne po capture_id.
- Dodana prosta strona /sandbox-test do testu bez pluginu Minecraft.

RENDER:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn --bind 0.0.0.0:$PORT app:app

Health Check Path:
/healthz

W Environment powinny byc:
PAYPAL_CLIENT_ID
PAYPAL_CLIENT_SECRET
PAYPAL_MODE=sandbox
PAYPAL_WEBHOOK_ID

PREMIUM_SERVER_KEY bedzie potrzebny dopiero przy podpinaniu pluginu Minecraft.

TEST:
1. Po deployu otworz:
   https://bezpieczna-strefa-full-pack.onrender.com/sandbox-test
2. Kliknij pakiet.
3. Zaloguj sie kontem PayPal Sandbox Buyer.
4. Zatwierdz platnosc.
5. Powinienes wrocic na strone z komunikatem o przyznaniu testowych Klejnotow.

UWAGA:
- Nie wrzucaj Client Secret do GitHuba.
- Baza SQLite na darmowym Render jest nietrwala po restarcie/redeployu. To jest tylko Sandbox.
- Przed LIVE trzeba podlaczyc trwala baze danych i wygenerowac swiezy Client Secret.
