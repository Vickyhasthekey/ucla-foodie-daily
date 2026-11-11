from pathlib import Path
from urllib.parse import quote

from typing import Annotated

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.env import load_env
from app.game import (
    ALLERGEN_OPTIONS,
    DECK_SIZE,
    FOOD_RULES,
    LIKE_TARGET,
    MEAL_OPTIONS,
    apply_swipe,
    build_deck,
    card_payload,
    decode_guest_prefs,
    decode_session,
    dishes_from_keys,
    empty_session,
    encode_guest_prefs,
    encode_session,
    match_result,
)
from app.match import accepted_halls, group_by_meal, preference_from_name, preferences_from_wish, recommend
from app.service import (
    bump_concept_score,
    day_plan,
    ensure_menu,
    ensure_never,
    ensure_preference,
    get_restrictions,
    get_user_by_session,
    liked_concept_ids,
    list_never,
    list_preferences,
    merge_guest_prefs,
    never_ids,
    preference_ids,
    init_db,
    la_label,
    la_today,
    open_account,
    remove_never,
    save_day_plan,
    save_restrictions,
    save_wish,
    toggle_preference,
    unsubscribe,
)

COOKIE = "foodie_session"
GUEST_COOKIE = "foodie_guest"
SWIPE_COOKIE = "foodie_swipe"

load_env()
ROOT = Path(__file__).resolve().parent
app = FastAPI(title="UCLA Foodie Daily")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


init_db()


def viewer(request):
    return get_user_by_session(request.cookies.get(COOKIE, ""))


def safe_next(value):
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def page(request, name, context, status_code=200):
    context = dict(context)
    context["account"] = viewer(request)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def cookie_kwargs(request):
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": request.url.scheme == "https",
        "max_age": 60 * 60 * 24 * 400,
    }


def guest_prefs(request):
    return decode_guest_prefs(request.cookies.get(GUEST_COOKIE, ""))


def set_guest_cookie(response, request, restrictions, never, ready=False):
    response.set_cookie(
        GUEST_COOKIE,
        encode_guest_prefs(restrictions, never, ready=ready),
        **cookie_kwargs(request),
    )


def load_profile(request):
    user = viewer(request)
    guest = guest_prefs(request)
    if user:
        restrictions = get_restrictions(user["id"])
        restrictions["meals"] = guest.get("meals") or []
        restrictions["ready"] = bool(
            guest.get("ready")
            or restrictions["allergens"]
            or restrictions["rules"]
            or list_never(user["id"])
        )
        never = never_ids(user["id"])
        liked = liked_concept_ids(user["id"])
        return user, restrictions, never, liked
    return (
        None,
        {
            "allergens": guest["allergens"],
            "rules": guest["rules"],
            "meals": guest.get("meals") or [],
            "ready": guest.get("ready"),
        },
        guest["never"],
        [],
    )


def swipe_session(request):
    return decode_session(request.cookies.get(SWIPE_COOKIE, ""))


def set_swipe_cookie(response, request, session):
    response.set_cookie(SWIPE_COOKIE, encode_session(session), **cookie_kwargs(request))


def clear_swipe_cookie(response):
    response.delete_cookie(SWIPE_COOKIE)


def start_deck(request):
    _, restrictions, never, liked = load_profile(request)
    dishes = ensure_menu(la_today())
    deck = build_deck(dishes, liked, never, restrictions)
    return empty_session([card_payload(dish)["key"] for dish in deck])


def home_page(request, wish, error=""):
    user = viewer(request)
    menu_date = la_today()
    return page(
        request,
        "home.html",
        {
            "wish": wish,
            "error": error,
            "plan": day_plan(user["id"], menu_date) if user else [],
            "date_label": la_label(menu_date),
        },
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, wish: str = ""):
    user = viewer(request)
    if not wish and user and user["foods"]:
        wish = user["foods"]
    return home_page(request, wish)


@app.post("/", response_class=HTMLResponse)
def home_submit(request: Request, wish: str = Form("")):
    wish = wish.strip()
    if not wish:
        return home_page(request, "", "Type a few foods.")
    user = viewer(request)
    if user:
        save_wish(user["email"], wish)
    return RedirectResponse("/today?wish=" + quote(wish), status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account_form(request: Request, next: str = "/", save_prefs: str = "", mode: str = ""):
    user = viewer(request)
    saved = list_preferences(user["id"]) if user else []
    never_list = list_never(user["id"]) if user else []
    restrictions = get_restrictions(user["id"]) if user else {"allergens": [], "rules": []}
    menu_date = la_today()
    plan = day_plan(user["id"], menu_date) if user else []
    return page(
        request,
        "account.html",
        {
            "next": safe_next(next),
            "saved": saved,
            "never_list": never_list,
            "restrictions": restrictions,
            "plan": plan,
            "date_label": la_label(menu_date),
            "save_prefs": save_prefs == "1",
            "mode": "signin" if mode == "signin" else "create",
            "error": "",
        },
    )


@app.post("/account")
def account_submit(request: Request, email: str = Form(""), next: str = Form("/")):
    email = email.strip().lower()
    if "@" not in email:
        return page(
            request,
            "account.html",
            {
                "next": safe_next(next),
                "saved": [],
                "never_list": [],
                "restrictions": {"allergens": [], "rules": []},
                "plan": [],
                "date_label": "",
                "save_prefs": True,
                "mode": "create",
                "error": "Add an email.",
            },
        )
    user = open_account(email)
    merge_guest_prefs(user["id"], guest_prefs(request))
    response = RedirectResponse(safe_next(next), status_code=303)
    response.set_cookie(COOKIE, user["session_token"], **cookie_kwargs(request))
    return response


@app.post("/account/never/remove")
def account_never_remove(request: Request, preference: str = Form("")):
    user = viewer(request)
    if not user:
        return RedirectResponse("/account?save_prefs=1", status_code=303)
    remove_never(user["id"], preference.strip())
    return RedirectResponse("/account", status_code=303)


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(COOKIE)
    return response


@app.get("/signup")
@app.get("/start")
def old_signup():
    return RedirectResponse("/account", status_code=303)


def today_path(wish):
    return "/today?wish=" + quote(wish)


def matched_view(user, wish):
    menu_date = la_today()
    dishes = ensure_menu(menu_date)
    saved_rows = list_preferences(user["id"]) if user else []
    saved_ids = [row["id"] for row in saved_rows]
    also = [row["label"] for row in saved_rows if row["id"].lower() not in wish.lower()]
    match_wish = wish + ", " + ", ".join(saved_ids) if also else wish
    meals = group_by_meal(recommend(dishes, match_wish)["matched"])
    return menu_date, meals, also, saved_ids


def plan_return_path(wish, choices):
    path = today_path(wish)
    names = {
        "Breakfast": "plan_breakfast",
        "Lunch": "plan_lunch",
        "Dinner": "plan_dinner",
        "All day": "plan_allday",
    }
    parts = []
    for meal, key in names.items():
        halls = choices.get(meal) or []
        if isinstance(halls, str):
            halls = [halls]
        for hall in halls:
            hall = (hall or "").strip()
            if hall:
                parts.append(key + "=" + quote(hall))
    if parts:
        path += "&" + "&".join(parts)
    return path


@app.get("/today", response_class=HTMLResponse)
def today(
    request: Request,
    wish: str = "",
    save: str = "",
    plan_breakfast: str = "",
    plan_lunch: str = "",
    plan_dinner: str = "",
    plan_allday: Annotated[list[str], Query()] = [],
    pick: str = "",
):
    wish = wish.strip()
    if not wish:
        return RedirectResponse("/", status_code=303)
    user = viewer(request)
    if user and save:
        for preference_id in save.split(","):
            ensure_preference(user["id"], preference_id.strip())
        return RedirectResponse(today_path(wish), status_code=303)
    if user:
        save_wish(user["email"], wish)
    menu_date, meals, also, saved_ids = matched_view(user, wish)
    pending_plan = {
        "Breakfast": plan_breakfast,
        "Lunch": plan_lunch,
        "Dinner": plan_dinner,
        "All day": plan_allday,
    }
    if user and any(pending_plan.values()):
        chosen = accepted_halls(meals, pending_plan)
        if chosen:
            save_day_plan(user["id"], menu_date, chosen)
        return RedirectResponse(today_path(wish), status_code=303)
    wish_preferences = preferences_from_wish(wish)
    wish_ids = [item["id"] for item in wish_preferences]
    plan = day_plan(user["id"], menu_date) if user else []
    plan_choice = {}
    for item in plan:
        plan_choice.setdefault(item["meal"], []).append(item["hall"])
    return page(
        request,
        "today.html",
        {
            "wish": wish,
            "wish_query": quote(wish),
            "wish_save": ",".join(wish_ids),
            "wish_saved": bool(wish_ids) and set(wish_ids) <= set(saved_ids),
            "date_label": la_label(menu_date),
            "meals": meals,
            "also": also,
            "plan": plan,
            "plan_choice": plan_choice,
            "pick": pick == "1",
        },
    )


@app.post("/plan")
def save_plan(
    request: Request,
    wish: str = Form(""),
    Breakfast: str = Form(""),
    Lunch: str = Form(""),
    Dinner: str = Form(""),
    all_day: Annotated[list[str], Form(alias="All day")] = [],
):
    wish = wish.strip()
    choices = {"Breakfast": Breakfast, "Lunch": Lunch, "Dinner": Dinner, "All day": all_day}
    user = viewer(request)
    picked = []
    for value in choices.values():
        picked.extend([value] if isinstance(value, str) else value)
    if not any((hall or "").strip() for hall in picked):
        return RedirectResponse(today_path(wish) + "&pick=1", status_code=303)
    if not user:
        return RedirectResponse(
            "/account?next=" + quote(plan_return_path(wish, choices)),
            status_code=303,
        )
    menu_date, meals, _, _ = matched_view(user, wish)
    chosen = accepted_halls(meals, choices)
    if chosen:
        save_day_plan(user["id"], menu_date, chosen)
    return RedirectResponse(today_path(wish), status_code=303)


@app.post("/favorite")
def favorite(request: Request, wish: str = Form("")):
    wish = wish.strip()
    user = viewer(request)
    target = today_path(wish)
    wish_ids = [item["id"] for item in preferences_from_wish(wish)]
    if not user:
        signed_in = target + "&save=" + quote(",".join(wish_ids))
        return RedirectResponse("/account?next=" + quote(signed_in), status_code=303)
    already = set(preference_ids(user["id"]))
    if wish_ids and set(wish_ids) <= already:
        for preference_id in wish_ids:
            toggle_preference(user["id"], preference_id)
    else:
        for preference_id in wish_ids:
            ensure_preference(user["id"], preference_id)
    return RedirectResponse(target, status_code=303)


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(request: Request, token: str = ""):
    return page(
        request,
        "unsubscribe.html",
        {"token": token, "done": False, "missing": not token, "user": None},
    )


@app.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_submit(request: Request, token: str = Form("")):
    user = unsubscribe(token) if token else None
    return page(
        request,
        "unsubscribe.html",
        {"token": token, "done": True, "user": user, "missing": user is None},
    )


@app.get("/match", response_class=HTMLResponse)
def match_entry(request: Request, edit: str = ""):
    user, restrictions, never, _ = load_profile(request)
    if edit == "1" or not restrictions.get("ready"):
        return page(
            request,
            "match_restrict.html",
            {
                "allergen_options": ALLERGEN_OPTIONS,
                "food_rules": FOOD_RULES,
                "meal_options": MEAL_OPTIONS,
                "restrictions": {
                    "allergens": restrictions.get("allergens") or [],
                    "rules": restrictions.get("rules") or [],
                    "meals": restrictions.get("meals") or [],
                },
            },
        )
    response = RedirectResponse("/match/play", status_code=303)
    session = start_deck(request)
    set_swipe_cookie(response, request, session)
    return response


@app.post("/match/restrict")
async def match_restrict(request: Request):
    form = await request.form()
    allergens = [str(value) for value in form.getlist("allergen")]
    rules = [str(value) for value in form.getlist("rule")]
    meals = [str(value) for value in form.getlist("meal")]
    user = viewer(request)
    guest = guest_prefs(request)
    restrictions = {"allergens": allergens, "rules": rules, "meals": meals, "ready": True}
    if user:
        save_restrictions(user["id"], allergens, rules)
        never = never_ids(user["id"])
    else:
        never = guest.get("never") or []
    response = RedirectResponse("/match/play", status_code=303)
    set_guest_cookie(response, request, restrictions, never, ready=True)
    # Rebuild deck with the restrictions just chosen (cookies are not readable until the next request).
    dishes = ensure_menu(la_today())
    liked = liked_concept_ids(user["id"]) if user else []
    deck = build_deck(dishes, liked, never, restrictions)
    set_swipe_cookie(response, request, empty_session([card_payload(dish)["key"] for dish in deck]))
    return response


@app.get("/match/play", response_class=HTMLResponse)
def match_play(request: Request):
    user, restrictions, never, liked = load_profile(request)
    if not restrictions.get("ready"):
        return RedirectResponse("/match", status_code=303)
    session = swipe_session(request)
    if not session.get("deck"):
        session = start_deck(request)
    likes = session.get("likes") or []
    if len(likes) >= LIKE_TARGET or int(session.get("index") or 0) >= len(session.get("deck") or []):
        return RedirectResponse("/match/result", status_code=303)
    dishes = ensure_menu(la_today())
    index = int(session.get("index") or 0)
    deck = session.get("deck") or []
    card = None
    if index < len(deck):
        current = dishes_from_keys([deck[index]], dishes)[0]
        card = card_payload(current)
    response = page(
        request,
        "match_play.html",
        {
            "card": card,
            "like_target": LIKE_TARGET,
            "liked_count": len(likes),
            "remaining": max(0, len(deck) - index),
            "can_undo": bool(session.get("undo")),
            "meal_filter": restrictions.get("meals") or [],
            "show_save_prompt": (not user) and bool(session.get("nevers") or likes),
        },
    )
    set_swipe_cookie(response, request, session)
    return response


@app.post("/match/play")
def match_play_submit(request: Request, action: str = Form("pass")):
    user, restrictions, never, _ = load_profile(request)
    session = swipe_session(request)
    if not session.get("deck"):
        session = start_deck(request)
    dishes = ensure_menu(la_today())
    before_index = int(session.get("index") or 0)
    deck = session.get("deck") or []
    current_key = deck[before_index] if before_index < len(deck) else ""
    session, done = apply_swipe(session, action)
    if user and current_key and action in {"like", "pass", "never"}:
        dish = dishes_from_keys([current_key], dishes)[0]
        pref = preference_from_name(dish["name"])
        if pref:
            bump_concept_score(user["id"], pref["id"], "never" if action == "never" else action)
            if action == "never":
                ensure_never(user["id"], pref["id"])
    if not user and action == "never" and current_key:
        dish = dishes_from_keys([current_key], dishes)[0]
        pref = preference_from_name(dish["name"])
        guest = guest_prefs(request)
        never_list = list(guest.get("never") or [])
        if pref and pref["id"] not in never_list:
            never_list.append(pref["id"])
        response = RedirectResponse("/match/result" if done else "/match/play", status_code=303)
        set_guest_cookie(
            response,
            request,
            {
                "allergens": guest.get("allergens") or [],
                "rules": guest.get("rules") or [],
                "meals": guest.get("meals") or [],
            },
            never_list,
            ready=True,
        )
        set_swipe_cookie(response, request, session)
        return response
    response = RedirectResponse("/match/result" if done else "/match/play", status_code=303)
    set_swipe_cookie(response, request, session)
    return response


@app.get("/match/result", response_class=HTMLResponse)
def match_result_page(request: Request, pick: str = ""):
    user, restrictions, never, _ = load_profile(request)
    session = swipe_session(request)
    if not session.get("deck"):
        return RedirectResponse("/match", status_code=303)
    menu_date = la_today()
    dishes = ensure_menu(menu_date)
    liked = dishes_from_keys(session.get("likes") or [], dishes)
    meals, suggestions = match_result(
        liked,
        dishes,
        restrictions,
        never,
        session.get("passes") or [],
        session.get("nevers") or [],
    )
    plan = day_plan(user["id"], menu_date) if user else []
    plan_choice = {}
    for item in plan:
        plan_choice.setdefault(item["meal"], []).append(item["hall"])
    for meal, hall in suggestions.items():
        plan_choice.setdefault(meal, [hall])
        if meal != "All day":
            plan_choice[meal] = [hall]
        elif hall not in plan_choice[meal]:
            plan_choice[meal] = [hall]
    return page(
        request,
        "match_result.html",
        {
            "date_label": la_label(menu_date),
            "meals": meals,
            "plan_choice": plan_choice,
            "pick": pick == "1",
            "show_save_prompt": not user,
        },
    )


@app.post("/match/plan")
def match_save_plan(
    request: Request,
    Breakfast: str = Form(""),
    Lunch: str = Form(""),
    Dinner: str = Form(""),
    all_day: Annotated[list[str], Form(alias="All day")] = [],
):
    choices = {"Breakfast": Breakfast, "Lunch": Lunch, "Dinner": Dinner, "All day": all_day}
    user = viewer(request)
    picked = []
    for value in choices.values():
        picked.extend([value] if isinstance(value, str) else value)
    if not any((hall or "").strip() for hall in picked):
        return RedirectResponse("/match/result?pick=1", status_code=303)
    if not user:
        return RedirectResponse(
            "/account?next=" + quote("/match/result") + "&save_prefs=1",
            status_code=303,
        )
    session = swipe_session(request)
    dishes = ensure_menu(la_today())
    liked = dishes_from_keys(session.get("likes") or [], dishes)
    _, restrictions, never, _ = load_profile(request)
    meals, _ = match_result(
        liked,
        dishes,
        restrictions,
        never,
        session.get("passes") or [],
        session.get("nevers") or [],
    )
    chosen = accepted_halls(meals, choices)
    if chosen:
        save_day_plan(user["id"], la_today(), chosen)
    response = RedirectResponse("/", status_code=303)
    clear_swipe_cookie(response)
    return response


@app.get("/health")
def health():
    return {"ok": True}
