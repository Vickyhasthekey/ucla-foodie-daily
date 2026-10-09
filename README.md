# UCLA Foodie Daily

A website for the dining-hall email that currently runs as three n8n workflows. Subscribers name the foods they want. Each morning at 7:00 Pacific, the job reads UCLA’s menu, matches those foods, and emails the halls that are serving them.

Open `index.html` in a browser to see the imported pages. Nothing on this site sends email yet.

## What moved over

| n8n workflow | What it does | On this site |
|---|---|---|
| Foodie Signup (Form) | Email, wanted foods, optional preference | [signup.html](signup.html) |
| Vicky_Foodie_Test | 7:00am menu match and MailerSend email | [src/email.js](src/email.js), [preview.html](preview.html) |
| Foodie Unsubscribe | Remove that email and show a confirmation | [unsubscribe.html](unsubscribe.html) |

The full step-by-step, including the assistant prompt and the rules the email follows, is in [docs/process.md](docs/process.md).

## Not in this repo

Subscriber addresses stay in n8n’s data table. API keys for OpenRouter and MailerSend stay in n8n credentials. This repository has the process, not the secrets or the mailing list.
