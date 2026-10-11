# UCLA Foodie Daily

The product lives on this website. Type what you feel like eating, and see your matching dining hall today.

n8n is not part of this app. Old subscriber rows stay in n8n and are not imported.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8765
```

Open http://127.0.0.1:8765

The database is `data/foodie.db` (not committed). Looking up a hall does not need an account. Saving a dish stores the food behind it (beef also means steak and the other similar words) and that requires signing in. The same email opens the same account. Copy `.env.example` to `.env` when you want the morning job to send mail. The app reads that file on startup. The first match downloads a small language model.

## Morning email

```bash
python -m app.daily
```

That saves today’s UCLA menu and writes one email per active subscriber into the local outbox. Set `MAILERSEND_API_KEY` if those emails should actually send. See `.env.example`. A 7:00am Pacific cron can run the same command.

Closed days produce no email. Matching compares the words they typed with today's dish names.
