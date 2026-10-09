# UCLA Foodie Daily process

Imported from the live n8n workflows on production (`n8n.qurio.pro`):

- `Foodie Signup (Form)` — `3OAVaeLWjsvabw6X`
- `Vicky_Foodie_Test` — `YelGHpl6lP1EjL8r`
- `Foodie Unsubscribe` — `AiIc4mhS2JxnSuOL`

Subscriber rows live in the n8n Data Table **Foodie Subscribers** (`i7VKBvqusBPTxJRY`), columns `email`, `foods`, and `pref`.

## 1. Sign up

Form title: **UCLA Foodie Daily - Sign Up**

Description: Get a daily email showing which dining hall has your favorite foods (and height-boosting picks when they're not on the menu).

| Field | Required | Example |
|---|---|---|
| Email | yes | you@g.ucla.edu |
| Foods you want | yes | beef, salmon, tiramisu |
| If not available, what should we recommend? | no | digestion, grow taller, premium |

On submit, the workflow tells the person: "You're subscribed! You'll get your first personalized dining pick tomorrow morning at 7am."

It writes one row (`email`, `foods`, `pref`), then deletes rows with that same email. On this website, that second step means **keep the newest signup for that address**. The n8n delete runs after the insert and matches every row with that email, so a working delete would also remove the row just written. The site should replace the previous foods and preference instead.

## 2. Morning email

`Vicky_Foodie_Test` is scheduled with `triggerAtHour: 7`. Recent runs start at 14:00 UTC, which is 7:00am Pacific.

1. Fetch `https://dining.ucla.edu/menus-at-a-glance/?date=YYYY-MM-DD` using today’s date in `America/Los_Angeles`.
2. Turn the page into `today` plus `menu_text`. Each menu line is `Hall | Meal | Dish`. If the halls are closed, `menu_text` is `(no dining service today)` or empty.
3. Load every subscriber.
4. For each subscriber, ask the model `openai/gpt-oss-20b:free` on OpenRouter. The system prompt is in `src/email.js`.
5. Parse the JSON reply and render HTML plus plain text.
6. Send only when `service_today` is true. The If node drops closed days before MailerSend.
7. Send through MailerSend as `UCLA Foodie Daily <noreply@qurio.pro>`. Subject: `🍽️ Today's UCLA dining picks · {today}`.

Matching rules from the prompt:

- Use only dishes that appear on that day’s menu, with the exact dish name.
- Wanted foods include synonyms (bulgogi, carne asada, and brisket count as beef; ribeye and sirloin count as steak; lox counts as salmon).
- List every match. Do not add dishes that are not matches.
- If a preference is set, also suggest 3–5 other dishes: grow taller → protein, calcium, vitamin D; digestion → easy to digest; premium → seafood, steak, prime cuts.
- Suggestions never repeat a matched dish. With no preference, there are no suggestions.
- Group by dish. One line per dish, halls and meals merged: `Dish — Hall (Meal), Hall (Meal)`.

The email then has one of these openings:

- Closed: a short no-service note. This version is built, then the If node skips sending.
- Favorites and suggestions: “Good morning! Here's what's good for you today.”
- Favorites only: “Good morning! Here's where to find your favorite foods today.”
- Suggestions only: “Good morning! Today's menu doesn't have your picks — but here's what to try.”
- Neither: “Good morning! Today's menu doesn't have your picks today.”

The footer links to update preferences and to unsubscribe.

The live **Extract menu** node is still the empty n8n template (`myNewField = 1`). Later nodes expect `today` and `menu_text`. The website needs a real extractor that produces those two fields. That extractor is not in the n8n node today.

## 3. Unsubscribe

`GET /webhook/foodie-unsubscribe?email=...` deletes subscriber rows with that email and returns an HTML page: “You've been unsubscribed” plus a link back to signup.

## Why this is moving to a website

The morning job still fires, fetches the menu page, and then stops. Postgres returns `42501 permission denied for table data_table_user_i7VKBvqusBPTxJRY` when n8n reads Foodie Subscribers. Signup fails on the same table at the delete step. The website is the place to keep the signup, the 7:00am match, and unsubscribe without that data table.
