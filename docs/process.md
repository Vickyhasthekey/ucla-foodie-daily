# UCLA Foodie Daily

The website is the product. A person types what they feel like eating, and the site matches that to today's UCLA dining halls.

## What a person does

1. Look up a hall with no account, or sign in with an email. The same email opens that account again.
2. Type foods such as beef, salmon, tiramisu. Today's page lists the dining halls that match.
3. Save a dish. That stores the food behind it. Steak saves as beef, with the similar words steak, beef, bulgogi, brisket, carne asada, ribeye, and sirloin. Saving requires signing in.

Matching uses a local embedding model (`BAAI/bge-small-en-v1.5`). A signed-in lookup also includes the foods they always want. Those foods are rows in `saved_preferences`.

## Morning job

`python -m app.daily` reads today's UCLA menu for the Los Angeles date and writes an outbox row for each active subscriber who wrote what they want. It sends through MailerSend only when `MAILERSEND_API_KEY` is set. If the halls are closed, it does not send.

## Tables

- `users` — email, the words they typed, unsubscribe token, active flag
- `dishes` — today's menu, used to build the matches
- `outbox` — the email that would go out
