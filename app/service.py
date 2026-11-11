import os
import secrets
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.db import connect, init_db, now_iso
from app.mailer import render_email, send_mailersend
from app.match import MEAL_ORDER, lookup_preference, recommend
from app.menu import fetch_boutique_dishes, fetch_menu_html, parse_menu_html

LA = ZoneInfo("America/Los_Angeles")


def la_today():
    return datetime.now(LA).date().isoformat()


def la_label(menu_date):
    day = datetime.strptime(menu_date, "%Y-%m-%d")
    return day.strftime("%A, %B ") + str(day.day)


def base_url():
    return os.environ.get("APP_BASE_URL", "http://127.0.0.1:8765").rstrip("/")


def upsert_user(email):
    init_db()
    email = email.strip().lower()
    stamp = now_iso()
    with connect() as conn:
        existing = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE users SET active = 1, updated_at = ? WHERE id = ?",
                (stamp, existing["id"]),
            )
            return conn.execute("SELECT * FROM users WHERE id = ?", (existing["id"],)).fetchone()
        token = secrets.token_urlsafe(24)
        conn.execute(
            """
            INSERT INTO users (email, foods, pref, unsubscribe_token, active, created_at, updated_at)
            VALUES (?, '', '', ?, 1, ?, ?)
            """,
            (email, token, stamp, stamp),
        )
        return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def save_wish(email, wish):
    wish = wish.strip()
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            "UPDATE users SET foods = ?, pref = ?, updated_at = ? WHERE email = ?",
            (wish, wish, stamp, email.strip().lower()),
        )
    return get_user(email)


def open_account(email):
    user = upsert_user(email)
    if user["session_token"]:
        return user
    token = secrets.token_urlsafe(24)
    with connect() as conn:
        conn.execute(
            "UPDATE users SET session_token = ?, updated_at = ? WHERE id = ?",
            (token, now_iso(), user["id"]),
        )
    return get_user(email)


def get_user_by_session(token):
    if not token:
        return None
    init_db()
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE session_token = ?",
            (token,),
        ).fetchone()


def list_preferences(user_id):
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT preference, label, words FROM saved_preferences
            WHERE user_id = ? ORDER BY id
            """,
            (user_id,),
        ).fetchall()
    return [
        {"id": row["preference"], "label": row["label"], "words": row["words"]}
        for row in rows
    ]


def preference_ids(user_id):
    return [row["id"] for row in list_preferences(user_id)]


def toggle_preference(user_id, preference_id):
    spec = lookup_preference(preference_id)
    if not spec:
        return False
    init_db()
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM saved_preferences WHERE user_id = ? AND preference = ?",
            (user_id, spec["id"]),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM saved_preferences WHERE id = ?", (existing["id"],))
            return False
        conn.execute(
            """
            INSERT INTO saved_preferences (user_id, preference, label, words, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, spec["id"], spec["label"], ", ".join(spec["words"]), now_iso()),
        )
        return True


def ensure_preference(user_id, preference_id):
    if preference_id in preference_ids(user_id):
        return
    toggle_preference(user_id, preference_id)


def save_day_plan(user_id, menu_date, choices):
    init_db()
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            "DELETE FROM day_plans WHERE user_id = ? AND menu_date = ?",
            (user_id, menu_date),
        )
        for meal in MEAL_ORDER:
            halls = choices.get(meal) or []
            if isinstance(halls, str):
                halls = [halls]
            for hall in halls:
                hall = (hall or "").strip()
                if not hall:
                    continue
                conn.execute(
                    """
                    INSERT INTO day_plans (user_id, menu_date, meal, hall, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, menu_date, meal, hall, stamp),
                )


def day_plan(user_id, menu_date):
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT meal, hall FROM day_plans
            WHERE user_id = ? AND menu_date = ?
            ORDER BY id
            """,
            (user_id, menu_date),
        ).fetchall()
    order = {meal: index for index, meal in enumerate(MEAL_ORDER)}
    items = [{"meal": row["meal"], "hall": row["hall"]} for row in rows]
    items.sort(key=lambda item: order.get(item["meal"], 9))
    return items


def list_plans(user_id):
    """Every saved day, including ones the account page does not show.

    Older rows stay in day_plans so a later recommendation model can train on them.
    """
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT menu_date, meal, hall FROM day_plans
            WHERE user_id = ? ORDER BY menu_date DESC, id
            """,
            (user_id,),
        ).fetchall()
    days = []
    grouped = {}
    for row in rows:
        if row["menu_date"] not in grouped:
            grouped[row["menu_date"]] = []
            days.append(row["menu_date"])
        grouped[row["menu_date"]].append({"meal": row["meal"], "hall": row["hall"]})
    order = {meal: index for index, meal in enumerate(MEAL_ORDER)}
    return [
        {
            "date": day,
            "label": la_label(day),
            "meals": sorted(grouped[day], key=lambda item: order.get(item["meal"], 9)),
        }
        for day in days
    ]


def get_user(email):
    init_db()
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()


def unsubscribe(token):
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE unsubscribe_token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE users SET active = 0, updated_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
        return row


def store_menu(menu_date, dishes):
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM dishes WHERE menu_date = ?", (menu_date,))
        rows = []
        seen = set()
        for dish in dishes:
            key = (dish["meal"], dish["hall"], dish["station"], dish["name"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (
                    menu_date,
                    dish["meal"],
                    dish["hall"],
                    dish["station"],
                    dish["name"],
                    dish["recipe_id"],
                    ",".join(dish["tags"]),
                )
            )
        conn.executemany(
            """
            INSERT INTO dishes (menu_date, meal, hall, station, name, recipe_id, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _dishes_from_rows(rows):
    dishes = []
    for row in rows:
        dishes.append(
            {
                "meal": row["meal"],
                "hall": row["hall"],
                "station": row["station"],
                "name": row["name"],
                "recipe_id": row["recipe_id"],
                "tags": [tag for tag in row["tags"].split(",") if tag],
            }
        )
    return dishes


def load_menu(menu_date):
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT meal, hall, station, name, recipe_id, tags
            FROM dishes WHERE menu_date = ?
            ORDER BY id
            """,
            (menu_date,),
        ).fetchall()
    return _dishes_from_rows(rows)


def menu_ready(menu_date):
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT boutique FROM menu_days WHERE menu_date = ?",
            (menu_date,),
        ).fetchone()
    return bool(row and row["boutique"])


def mark_menu(menu_date):
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO menu_days (menu_date, boutique) VALUES (?, 1)
            ON CONFLICT(menu_date) DO UPDATE SET boutique = 1
            """,
            (menu_date,),
        )


def ensure_menu(menu_date):
    init_db()
    with connect() as conn:
        ready = conn.execute(
            "SELECT boutique FROM menu_days WHERE menu_date = ?",
            (menu_date,),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT meal, hall, '' AS station, name, '' AS recipe_id, '' AS tags
            FROM dishes WHERE menu_date = ?
            ORDER BY id
            """,
            (menu_date,),
        ).fetchall()
    if rows and ready and ready["boutique"]:
        return _dishes_from_rows(rows)
    dishes = parse_menu_html(fetch_menu_html(menu_date))
    boutique_ok = False
    try:
        dishes.extend(fetch_boutique_dishes(menu_date))
        boutique_ok = True
    except Exception:
        boutique_ok = False
    if dishes:
        store_menu(menu_date, dishes)
    if boutique_ok:
        mark_menu(menu_date)
    return dishes


def build_for_user(user, dishes, menu_date):
    recommendation = recommend(dishes, user["foods"])
    signup_url = base_url() + "/signup?email=" + quote(user["email"])
    unsubscribe_url = base_url() + "/unsubscribe?token=" + user["unsubscribe_token"]
    message = render_email(la_label(menu_date), recommendation, signup_url, unsubscribe_url)
    message["recommendation"] = recommendation
    return message


def run_daily(menu_date=None, send=True):
    init_db()
    menu_date = menu_date or la_today()
    dishes = ensure_menu(menu_date)
    with connect() as conn:
        users = conn.execute("SELECT * FROM users WHERE active = 1").fetchall()
    sent = 0
    stored = 0
    for user in users:
        if not (user["foods"] or "").strip():
            continue
        message = build_for_user(user, dishes, menu_date)
        if not message["service_today"]:
            continue
        with connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO outbox (user_id, menu_date, subject, body_html, body_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    menu_date,
                    message["subject"],
                    message["html"],
                    message["text"],
                    now_iso(),
                ),
            )
            inserted = cursor.rowcount == 1
            outbox_id = cursor.lastrowid
        if not inserted:
            continue
        stored += 1
        if send and send_mailersend(user["email"], message["subject"], message["html"], message["text"]):
            with connect() as conn:
                conn.execute("UPDATE outbox SET sent_at = ? WHERE id = ?", (now_iso(), outbox_id))
            sent += 1
    return {"date": menu_date, "dishes": len(dishes), "stored": stored, "sent": sent}


def get_restrictions(user_id):
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT kind, value FROM user_restrictions WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
    allergens = []
    rules = []
    for row in rows:
        if row["kind"] == "allergen":
            allergens.append(row["value"])
        elif row["kind"] == "rule":
            rules.append(row["value"])
    return {"allergens": allergens, "rules": rules}


def save_restrictions(user_id, allergens, rules):
    init_db()
    stamp = now_iso()
    with connect() as conn:
        conn.execute("DELETE FROM user_restrictions WHERE user_id = ?", (user_id,))
        for value in allergens or []:
            value = (value or "").strip().lower()
            if not value:
                continue
            conn.execute(
                """
                INSERT INTO user_restrictions (user_id, kind, value, created_at)
                VALUES (?, 'allergen', ?, ?)
                """,
                (user_id, value, stamp),
            )
        for value in rules or []:
            value = (value or "").strip().lower()
            if not value:
                continue
            conn.execute(
                """
                INSERT INTO user_restrictions (user_id, kind, value, created_at)
                VALUES (?, 'rule', ?, ?)
                """,
                (user_id, value, stamp),
            )


def list_never(user_id):
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT preference, label, words FROM never_preferences
            WHERE user_id = ? ORDER BY id
            """,
            (user_id,),
        ).fetchall()
    return [
        {"id": row["preference"], "label": row["label"], "words": row["words"]}
        for row in rows
    ]


def never_ids(user_id):
    return [row["id"] for row in list_never(user_id)]


def ensure_never(user_id, preference_id):
    spec = lookup_preference(preference_id)
    if not spec:
        return
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO never_preferences
            (user_id, preference, label, words, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, spec["id"], spec["label"], ", ".join(spec["words"]), now_iso()),
        )


def remove_never(user_id, preference_id):
    init_db()
    with connect() as conn:
        conn.execute(
            "DELETE FROM never_preferences WHERE user_id = ? AND preference = ?",
            (user_id, preference_id),
        )


def bump_concept_score(user_id, preference_id, signal):
    if signal not in {"like", "pass", "never"}:
        return
    spec = lookup_preference(preference_id)
    if not spec:
        return
    column = {"like": "like_n", "pass": "pass_n", "never": "never_n"}[signal]
    init_db()
    stamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO concept_scores (user_id, preference, like_n, pass_n, never_n, updated_at)
            VALUES (?, ?, 0, 0, 0, ?)
            ON CONFLICT(user_id, preference) DO NOTHING
            """,
            (user_id, spec["id"], stamp),
        )
        conn.execute(
            f"""
            UPDATE concept_scores
            SET {column} = {column} + 1, updated_at = ?
            WHERE user_id = ? AND preference = ?
            """,
            (stamp, user_id, spec["id"]),
        )


def liked_concept_ids(user_id):
    init_db()
    ids = preference_ids(user_id)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT preference, like_n, never_n FROM concept_scores
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    scored = []
    for row in rows:
        if (row["never_n"] or 0) > (row["like_n"] or 0):
            continue
        if (row["like_n"] or 0) > 0:
            scored.append(row["preference"])
    for preference_id in ids:
        if preference_id not in scored:
            scored.append(preference_id)
    return scored


def merge_guest_prefs(user_id, guest):
    allergens = guest.get("allergens") or []
    rules = guest.get("rules") or []
    if allergens or rules:
        current = get_restrictions(user_id)
        save_restrictions(
            user_id,
            sorted(set(current["allergens"] + allergens)),
            sorted(set(current["rules"] + rules)),
        )
    for preference_id in guest.get("never") or []:
        ensure_never(user_id, preference_id)
