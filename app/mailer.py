import json
import os
from html import escape
from urllib.request import Request, urlopen


def _places(item):
    return ", ".join(item["places"])


def _items_html(items):
    rows = []
    for item in items:
        rows.append(
            "<li><strong>" + escape(item["name"]) + "</strong> — " + escape(_places(item)) + "</li>"
        )
    if not rows:
        return ""
    return '<ul style="line-height:1.8;padding-left:20px;font-size:15px;margin-top:6px">' + "".join(rows) + "</ul>"


def _section(title, items):
    body = _items_html(items)
    if not body:
        return ""
    return '<p style="margin:18px 0 2px;font-size:15px;font-weight:700">' + escape(title) + "</p>" + body


def _halls_html(halls):
    parts = []
    for hall in halls:
        items = [
            {"name": dish["name"], "places": [dish["meal"]] if dish["meal"] else []}
            for dish in hall["dishes"]
        ]
        parts.append(_section(hall["hall"], items))
    return "".join(parts)


def render_email(today, recommendation, signup_url, unsubscribe_url):
    from app.match import group_by_hall

    matched = recommendation["matched"]
    halls = group_by_hall(matched)
    if not recommendation["service_today"]:
        intro = "Good morning! There's no dining service today."
        body = ""
    elif halls:
        names = ", ".join(hall["hall"] for hall in halls)
        intro = f"Good morning! Matching dining halls: {names}."
        body = _halls_html(halls)
    else:
        intro = "Good morning! No dining hall matches today."
        body = ""
    footer = (
        "You're receiving this because you subscribed to UCLA Foodie Daily.<br>"
        f'<a href="{escape(signup_url)}">Update my preferences</a>'
        " · "
        f'<a href="{escape(unsubscribe_url)}">Unsubscribe</a>'
    )
    html = (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;max-width:560px;color:#1a1a1a">'
        "<h2>UCLA Foodie Daily</h2>"
        f'<p style="color:#8a8a8a">{escape(today)}</p>'
        f"<p>{escape(intro)}</p>{body}"
        f'<p style="color:#888;font-size:12px">{footer}</p></div>'
    )
    text_lines = [intro, ""]
    for hall in halls:
        text_lines.append(hall["hall"])
        for dish in hall["dishes"]:
            meal = f" ({dish['meal']})" if dish["meal"] else ""
            text_lines.append(f"- {dish['name']}{meal}")
        text_lines.append("")
    text_lines.append("Update your picks: " + signup_url)
    text_lines.append("Unsubscribe: " + unsubscribe_url)
    return {
        "service_today": recommendation["service_today"],
        "subject": f"Today's UCLA dining picks · {today}",
        "html": html,
        "text": "\n".join(text_lines),
        "intro": intro,
    }


def send_mailersend(to_email, subject, html, text):
    api_key = os.environ.get("MAILERSEND_API_KEY", "").strip()
    sender = os.environ.get("MAILERSEND_FROM", "noreply@qurio.pro").strip()
    if not api_key:
        return False
    payload = {
        "from": {"email": sender, "name": "UCLA Foodie Daily"},
        "to": [{"email": to_email}],
        "subject": subject,
        "html": html,
        "text": text,
    }
    request = Request(
        "https://api.mailersend.com/v1/email",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return 200 <= response.status < 300
