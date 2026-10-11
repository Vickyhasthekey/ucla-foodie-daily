from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.env import load_env
from app.match import accepted_halls, group_by_meal, preferences_from_wish, recommend
from app.service import (
    day_plan,
    ensure_menu,
    ensure_preference,
    get_user_by_session,
    list_plans,
    list_preferences,
    preference_ids,
    init_db,
    la_label,
    la_today,
    open_account,
    save_day_plan,
    save_wish,
    toggle_preference,
    unsubscribe,
)

COOKIE = "foodie_session"

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


@app.get("/", response_class=HTMLResponse)
def home(request: Request, wish: str = ""):
    user = viewer(request)
    if not wish and user and user["foods"]:
        wish = user["foods"]
    return page(request, "home.html", {"wish": wish, "error": ""})


@app.post("/", response_class=HTMLResponse)
def home_submit(request: Request, wish: str = Form("")):
    wish = wish.strip()
    if not wish:
        return page(request, "home.html", {"wish": "", "error": "Type a few foods."})
    user = viewer(request)
    if user:
        save_wish(user["email"], wish)
    return RedirectResponse("/today?wish=" + quote(wish), status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account_form(request: Request, next: str = "/"):
    user = viewer(request)
    saved = list_preferences(user["id"]) if user else []
    plans = list_plans(user["id"]) if user else []
    return page(
        request,
        "account.html",
        {"next": safe_next(next), "saved": saved, "plans": plans, "error": ""},
    )


@app.post("/account")
def account_submit(request: Request, email: str = Form(""), next: str = Form("/")):
    email = email.strip().lower()
    if "@" not in email:
        return page(
            request,
            "account.html",
            {"next": safe_next(next), "saved": [], "plans": [], "error": "Add an email."},
        )
    user = open_account(email)
    response = RedirectResponse(safe_next(next), status_code=303)
    response.set_cookie(
        COOKIE,
        user["session_token"],
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 400,
    )
    return response


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
    }
    parts = []
    for meal, key in names.items():
        hall = (choices.get(meal) or "").strip()
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
    }
    if user and any(pending_plan.values()):
        chosen = accepted_halls(meals, pending_plan)
        if chosen:
            save_day_plan(user["id"], menu_date, chosen)
        return RedirectResponse(today_path(wish), status_code=303)
    wish_preferences = preferences_from_wish(wish)
    wish_ids = [item["id"] for item in wish_preferences]
    plan = day_plan(user["id"], menu_date) if user else []
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
            "plan_choice": {item["meal"]: item["hall"] for item in plan},
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
):
    wish = wish.strip()
    choices = {"Breakfast": Breakfast, "Lunch": Lunch, "Dinner": Dinner}
    user = viewer(request)
    if not any(hall.strip() for hall in choices.values()):
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


@app.get("/health")
def health():
    return {"ok": True}
