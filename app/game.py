import json
import re
from urllib.parse import quote

from app.match import (
    CONCEPTS,
    MEAL_ORDER,
    _contains,
    accepted_halls,
    group_by_meal,
    preference_from_name,
)

DECK_SIZE = 12
LIKE_TARGET = 3
CLOSE_SHARE = 0.4
POPULAR_SHARE = 0.3

ALLERGEN_OPTIONS = [
    ("dairy", "Dairy"),
    ("egg", "Egg"),
    ("fish", "Fish"),
    ("shellfish", "Shellfish"),
    ("peanut", "Peanut"),
    ("tree nut", "Tree nut"),
    ("wheat", "Wheat / gluten"),
    ("soy", "Soy"),
    ("sesame", "Sesame"),
]

FOOD_RULES = [
    ("no_chicken", "No chicken"),
    ("no_beef", "No beef"),
    ("no_pork", "No pork"),
    ("vegetarian", "Vegetarian"),
    ("vegan", "Vegan"),
]

RULE_BLOCK = {
    "no_chicken": ["chicken", "turkey"],
    "no_beef": ["beef", "steak", "bulgogi", "brisket", "carne asada", "ribeye", "sirloin"],
    "no_pork": ["pork", "bacon", "ham", "sausage"],
}

VEGAN_BLOCK = ["chicken", "turkey", "beef", "steak", "pork", "bacon", "ham", "sausage", "fish", "salmon", "shrimp", "tuna", "egg", "omelet", "yogurt", "cheese", "milk", "butter", "cream"]
VEGETARIAN_BLOCK = ["chicken", "turkey", "beef", "steak", "pork", "bacon", "ham", "sausage", "fish", "salmon", "shrimp", "tuna"]

POPULAR_CONCEPT_IDS = ["beef", "chicken", "fish", "dessert", "noodles", "vegetables"]


def dish_key(dish):
    return f"{dish['meal']}|{dish['hall']}|{dish['name']}"


def parse_dish_key(key):
    meal, hall, name = key.split("|", 2)
    return {"meal": meal, "hall": hall, "name": name, "station": "", "recipe_id": "", "tags": []}


def vibe_chips(dish):
    name = (dish.get("name") or "").lower()
    tags = [tag.lower() for tag in dish.get("tags") or []]
    chips = []
    if any(word in name for word in ("salad", "fruit", "yogurt", "greens")):
        chips.append("light")
    if any(word in name for word in ("burger", "fried", "pizza", "pasta", "steak", "bowl")):
        chips.append("hearty")
    if any(word in name for word in ("soup", "broth", "chili", "pho")) or "hot" in tags:
        chips.append("warm")
    if any(word in name for word in ("ice cream", "smoothie", "salad", "gazpacho")):
        chips.append("cool")
    if any(word in name for word in ("cake", "cookie", "brownie", "tiramisu", "pie", "chocolate")):
        chips.append("sweet")
    if any(word in name for word in ("spicy", "chili", "buffalo", "jalapeno")):
        chips.append("spicy")
    pref = preference_from_name(dish.get("name") or "")
    if pref and pref["id"] in {"beef", "chicken", "fish", "pork"}:
        chips.append(pref["label"].lower())
    seen = set()
    out = []
    for chip in chips:
        if chip not in seen:
            seen.add(chip)
            out.append(chip)
    return out[:3]


def allergen_chips(dish):
    chips = []
    for tag in dish.get("tags") or []:
        title = tag.strip()
        if not title:
            continue
        lower = title.lower()
        if "vegetarian" in lower or "vegan" in lower or "contain" in lower or "allerg" in lower:
            chips.append(title)
        elif any(key in lower for key, _ in ALLERGEN_OPTIONS):
            chips.append(title)
    return chips[:4]


def _blocked_by_rule(name, rules):
    lower = name.lower()
    if "vegan" in rules:
        return any(_contains(lower, word) for word in VEGAN_BLOCK)
    if "vegetarian" in rules:
        return any(_contains(lower, word) for word in VEGETARIAN_BLOCK)
    for rule in rules:
        words = RULE_BLOCK.get(rule) or []
        if any(_contains(lower, word) for word in words):
            return True
    return False


def _blocked_by_allergen(dish, allergens):
    if not allergens:
        return False
    blob = " ".join(dish.get("tags") or []).lower() + " " + (dish.get("name") or "").lower()
    for allergen in allergens:
        if allergen in blob:
            return True
        if allergen == "wheat" and ("gluten" in blob or "wheat" in blob):
            return True
        if allergen == "tree nut" and ("tree nut" in blob or "almond" in blob or "walnut" in blob or "cashew" in blob):
            return True
    return False


def _blocked_by_never(name, never_ids):
    pref = preference_from_name(name)
    if pref and pref["id"] in never_ids:
        return True
    return False


def filter_dishes(dishes, restrictions, never_ids):
    allergens = set(restrictions.get("allergens") or [])
    rules = set(restrictions.get("rules") or [])
    never = set(never_ids or [])
    kept = []
    for dish in dishes:
        if _blocked_by_rule(dish["name"], rules):
            continue
        if _blocked_by_allergen(dish, allergens):
            continue
        if _blocked_by_never(dish["name"], never):
            continue
        kept.append(dish)
    return kept


def _unique_by_name(dishes):
    seen = set()
    out = []
    for dish in dishes:
        key = dish["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(dish)
    return out


def _matches_concepts(dish, concept_ids):
    pref = preference_from_name(dish["name"])
    return bool(pref and pref["id"] in concept_ids)


def build_deck(dishes, liked_concept_ids, never_ids, restrictions):
    pool = _unique_by_name(filter_dishes(dishes, restrictions, never_ids))
    if not pool:
        return []
    liked = set(liked_concept_ids or [])
    close = [dish for dish in pool if liked and _matches_concepts(dish, liked)]
    popular_ids = set(POPULAR_CONCEPT_IDS)
    popular = [dish for dish in pool if _matches_concepts(dish, popular_ids)]
    fresh = [dish for dish in pool if not (liked and _matches_concepts(dish, liked))]

    close_n = max(1, int(DECK_SIZE * CLOSE_SHARE)) if liked else 0
    popular_n = max(1, int(DECK_SIZE * POPULAR_SHARE))
    deck = []
    used = set()

    def take(source, count):
        added = 0
        for dish in source:
            key = dish["name"].strip().lower()
            if key in used:
                continue
            used.add(key)
            deck.append(dish)
            added += 1
            if added >= count or len(deck) >= DECK_SIZE:
                return

    take(close, close_n)
    take(popular, popular_n)
    take(fresh, DECK_SIZE - len(deck))
    take(pool, DECK_SIZE - len(deck))
    return deck[:DECK_SIZE]


def card_payload(dish):
    return {
        "key": dish_key(dish),
        "name": dish["name"],
        "hall": dish["hall"],
        "meal": dish["meal"],
        "vibes": vibe_chips(dish),
        "allergens": allergen_chips(dish),
    }


def encode_guest_prefs(restrictions, never_ids, ready=False):
    return json.dumps(
        {
            "allergens": list(restrictions.get("allergens") or []),
            "rules": list(restrictions.get("rules") or []),
            "never": list(never_ids or []),
            "ready": bool(ready or restrictions.get("ready")),
        },
        separators=(",", ":"),
    )


def decode_guest_prefs(raw):
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    return {
        "allergens": [item for item in data.get("allergens") or [] if isinstance(item, str)],
        "rules": [item for item in data.get("rules") or [] if isinstance(item, str)],
        "never": [item for item in data.get("never") or [] if isinstance(item, str)],
        "ready": bool(data.get("ready")),
    }


def encode_session(session):
    return json.dumps(session, separators=(",", ":"))


def decode_session(raw):
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def empty_session(deck_keys):
    return {
        "deck": deck_keys,
        "index": 0,
        "likes": [],
        "passes": [],
        "nevers": [],
        "undo": [],
    }


def apply_swipe(session, action):
    deck = session.get("deck") or []
    index = int(session.get("index") or 0)
    if action == "undo":
        undo = session.get("undo") or []
        if not undo:
            return session, False
        last = undo.pop()
        kind = last.get("kind")
        key = last.get("key")
        bucket = {"like": "likes", "pass": "passes", "never": "nevers"}.get(kind)
        if bucket:
            values = session.get(bucket) or []
            if key in values:
                values.remove(key)
            session[bucket] = values
        session["undo"] = undo
        session["index"] = max(0, int(session.get("index") or 0) - 1)
        return session, False

    if index >= len(deck):
        return session, True
    key = deck[index]
    if action == "like":
        session.setdefault("likes", []).append(key)
        session.setdefault("undo", []).append({"kind": "like", "key": key})
    elif action == "never":
        session.setdefault("nevers", []).append(key)
        session.setdefault("undo", []).append({"kind": "never", "key": key})
    else:
        session.setdefault("passes", []).append(key)
        session.setdefault("undo", []).append({"kind": "pass", "key": key})
    session["index"] = index + 1
    done = len(session.get("likes") or []) >= LIKE_TARGET or session["index"] >= len(deck)
    return session, done


def dishes_from_keys(keys, menu_dishes):
    lookup = {dish_key(dish): dish for dish in menu_dishes}
    out = []
    for key in keys:
        dish = lookup.get(key)
        if dish:
            out.append(dish)
        else:
            out.append(parse_dish_key(key))
    return out


def similar_fill(liked_dishes, menu_dishes, restrictions, never_ids, exclude_names, limit=6):
    liked_concepts = set()
    for dish in liked_dishes:
        pref = preference_from_name(dish["name"])
        if pref:
            liked_concepts.add(pref["id"])
    if not liked_concepts:
        liked_concepts = set(POPULAR_CONCEPT_IDS[:3])
    pool = filter_dishes(menu_dishes, restrictions, never_ids)
    blocked = {name.strip().lower() for name in exclude_names}
    fill = []
    for dish in _unique_by_name(pool):
        if dish["name"].strip().lower() in blocked:
            continue
        if _matches_concepts(dish, liked_concepts):
            fill.append(dish)
        if len(fill) >= limit:
            break
    if len(fill) < limit:
        for dish in _unique_by_name(pool):
            if dish["name"].strip().lower() in blocked:
                continue
            if dish in fill:
                continue
            fill.append(dish)
            if len(fill) >= limit:
                break
    return fill


def match_result(liked_dishes, menu_dishes, restrictions, never_ids, passed_keys, never_keys):
    exclude = {dish["name"] for dish in liked_dishes}
    for key in (passed_keys or []) + (never_keys or []):
        exclude.add(parse_dish_key(key)["name"])
    fill = similar_fill(liked_dishes, menu_dishes, restrictions, never_ids, exclude)
    combined = liked_dishes + fill
    matched = []
    for dish in _unique_by_name(combined):
        matched.append(
            {
                "name": dish["name"],
                "places": [f"{dish['hall']} ({dish['meal']})"],
                "goals": [],
            }
        )
    # Merge places for same name across meals/halls from the full menu.
    by_name = {}
    order = []
    for dish in combined:
        key = dish["name"].strip().lower()
        place = f"{dish['hall']} ({dish['meal']})"
        if key not in by_name:
            by_name[key] = {"name": dish["name"], "places": [], "goals": []}
            order.append(key)
        if place not in by_name[key]["places"]:
            by_name[key]["places"].append(place)
    matched = [by_name[key] for key in order]
    meals = group_by_meal(matched)
    suggestions = {}
    for meal in meals:
        if meal["halls"]:
            suggestions[meal["meal"]] = meal["halls"][0]["hall"]
    return meals, suggestions


def concept_ids_from_dishes(dishes):
    ids = []
    seen = set()
    for dish in dishes:
        pref = preference_from_name(dish["name"])
        if pref and pref["id"] not in seen:
            seen.add(pref["id"])
            ids.append(pref["id"])
    return ids


def account_save_path():
    return "/account?next=" + quote("/match") + "&save_prefs=1"
