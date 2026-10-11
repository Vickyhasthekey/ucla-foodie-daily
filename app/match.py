import re

CONCEPTS = [
    {"id": "beef", "label": "Beef", "text": "beef steak bulgogi brisket carne asada", "words": ["beef", "steak", "bulgogi", "brisket", "carne asada", "ribeye", "sirloin"]},
    {"id": "chicken", "label": "Chicken", "text": "chicken poultry turkey", "words": ["chicken", "turkey"]},
    {"id": "fish", "label": "Fish", "text": "fish salmon seafood shrimp tuna", "words": ["salmon", "fish", "lox", "shrimp", "tuna"]},
    {"id": "sweet", "label": "Sweet breakfast", "text": "sweet breakfast pancakes french toast waffles", "words": ["pancake", "french toast", "waffle", "cinnamon"]},
    {"id": "eggs", "label": "Eggs", "text": "eggs omelet", "words": ["egg", "omelet"]},
    {"id": "vegetables", "label": "Vegetables", "text": "salad vegetables greens", "words": ["salad", "greens", "vegetable", "spinach", "kale"]},
    {"id": "soup", "label": "Soup", "text": "soup broth", "words": ["soup", "broth"]},
    {"id": "fruit", "label": "Fruit", "text": "yogurt fruit banana", "words": ["yogurt", "fruit", "banana", "berry"]},
    {"id": "grains", "label": "Grains", "text": "rice quinoa grain bowl", "words": ["rice", "quinoa", "bowl"]},
    {"id": "noodles", "label": "Noodles", "text": "pasta noodles", "words": ["pasta", "noodle", "soba"]},
    {"id": "flatbread", "label": "Flatbread", "text": "pizza flatbread", "words": ["pizza", "flatbread"]},
    {"id": "pork", "label": "Pork", "text": "pork bacon ham sausage", "words": ["pork", "bacon", "ham", "sausage"]},
    {"id": "dessert", "label": "Dessert", "text": "dessert cake cookie chocolate tiramisu pie", "words": ["cake", "cookie", "cupcake", "brownie", "tiramisu", "pie"]},
]

BROAD_PREFERENCES = {"flatbread", "grains", "noodles"}

STOPWORDS = {
    "a", "an", "the", "i", "me", "my", "we", "want", "something", "with", "and", "or",
    "for", "of", "to", "on", "in", "today", "please", "like", "feel", "feeling",
    "just", "some", "really", "very", "hearty", "light", "sweet", "easy", "premium",
    "dinner", "breakfast", "lunch", "warm", "plate", "dish", "food", "eat", "eating",
    "stomach", "hall",
}


def _contains(dish_name, needle):
    return re.search(
        rf"(?<![a-z]){re.escape(needle)}s?(?![a-z])",
        dish_name.lower(),
    ) is not None


def preference_from_name(name):
    hits = []
    for concept in CONCEPTS:
        if any(_contains(name, word) for word in concept["words"]):
            hits.append(concept)
    specific = [concept for concept in hits if concept["id"] not in BROAD_PREFERENCES]
    chosen = specific or hits
    if not chosen:
        tokens = content_tokens(name)
        if not tokens:
            return None
        word = max(tokens, key=len)
        return {"id": word, "label": word.title(), "words": [word]}
    best = max(chosen, key=lambda concept: max(len(word) for word in concept["words"] if _contains(name, word)))
    return {"id": best["id"], "label": best["label"], "words": list(best["words"])}


def preferences_from_wish(wish):
    parts = [part.strip() for part in (wish or "").split(",") if part.strip()] or [wish.strip()]
    found = []
    seen = set()
    for part in parts:
        pref = preference_from_name(part)
        if pref and pref["id"] not in seen:
            seen.add(pref["id"])
            found.append(pref)
    return found


def lookup_preference(preference_id):
    for concept in CONCEPTS:
        if concept["id"] == preference_id:
            return {"id": concept["id"], "label": concept["label"], "words": list(concept["words"])}
    if re.fullmatch(r"[a-z]{3,24}", preference_id or ""):
        return {"id": preference_id, "label": preference_id.title(), "words": [preference_id]}
    return None


def content_tokens(wish):
    tokens = []
    for raw in re.findall(r"[a-z][a-z']+", wish.lower()):
        if raw in STOPWORDS or len(raw) < 3 or raw in tokens:
            continue
        tokens.append(raw)
    return tokens


def group_dishes(dishes):
    grouped = {}
    order = []
    for dish in dishes:
        key = dish["name"].strip().lower()
        if key not in grouped:
            grouped[key] = {"name": dish["name"].strip(), "places": [], "tags": []}
            order.append(key)
        place = f"{dish['hall']} ({dish['meal']})"
        if place not in grouped[key]["places"]:
            grouped[key]["places"].append(place)
        for tag in dish.get("tags") or []:
            if tag not in grouped[key]["tags"]:
                grouped[key]["tags"].append(tag)
    return [grouped[key] for key in order]


def recommend(dishes, wish, score_fn=None):
    from app.semantic import score_query

    wish = (wish or "").strip()
    grouped = group_dishes(dishes)
    if not wish or not grouped:
        return {"matched": [], "suggested": [], "service_today": bool(dishes)}
    score_fn = score_fn or score_query
    parts = [part.strip() for part in wish.split(",") if part.strip()] or [wish]
    seen = set()
    matched = []
    for part in parts:
        concept_scores = score_fn(part, [concept["text"] for concept in CONCEPTS])
        best = max(concept_scores)
        words = []
        if best >= 0.6:
            for score, concept in zip(concept_scores, CONCEPTS):
                if score >= best - 0.02:
                    words.extend(concept["words"])
        typed = content_tokens(part)
        ranked = []
        for index, item in enumerate(grouped):
            concept_hits = sum(_contains(item["name"], word) for word in words)
            typed_hits = sum(_contains(item["name"], word) for word in typed)
            if concept_hits or typed_hits:
                ranked.append((typed_hits, concept_hits, -index, item))
        ranked.sort(reverse=True)
        kept = 0
        for _, _, _, item in ranked:
            key = item["name"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            picked = dict(item)
            picked["goals"] = []
            matched.append(picked)
            kept += 1
            if kept >= 3 or len(matched) >= 8:
                break
        if len(matched) >= 8:
            break
    return {"matched": matched, "suggested": [], "service_today": bool(dishes)}


MEAL_ORDER = ("Breakfast", "Lunch", "Dinner", "All day")


def _choice_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    halls = []
    for hall in value:
        hall = (hall or "").strip()
        if hall and hall not in halls:
            halls.append(hall)
    return halls


def accepted_halls(meals, choices):
    offered = {
        meal["meal"]: {hall["hall"] for hall in meal["halls"]}
        for meal in meals
    }
    kept = {}
    for meal in MEAL_ORDER:
        halls = [
            hall
            for hall in _choice_list(choices.get(meal))
            if hall in offered.get(meal, set())
        ]
        if meal != "All day":
            halls = halls[:1]
        if halls:
            kept[meal] = halls
    return kept


def group_by_meal(matched):
    buckets = {meal: {} for meal in MEAL_ORDER}
    hall_order = {meal: [] for meal in MEAL_ORDER}
    for item in matched:
        for place in item.get("places") or []:
            if place.endswith(")") and " (" in place:
                hall, meal = place.rsplit(" (", 1)
                meal = meal[:-1]
            else:
                hall, meal = place, ""
            if meal not in buckets:
                continue
            if hall not in buckets[meal]:
                buckets[meal][hall] = []
                hall_order[meal].append(hall)
            buckets[meal][hall].append({"name": item["name"]})
    meals = []
    for meal in MEAL_ORDER:
        halls = [
            {"hall": hall, "dishes": buckets[meal][hall]}
            for hall in hall_order[meal]
        ]
        halls.sort(key=lambda hall: (-len(hall["dishes"]), hall_order[meal].index(hall["hall"])))
        meals.append({"meal": meal, "halls": halls})
    return meals


def group_by_hall(matched):
    order = []
    groups = {}
    for item in matched:
        for place in item.get("places") or []:
            if place.endswith(")") and " (" in place:
                hall, meal = place.rsplit(" (", 1)
                meal = meal[:-1]
            else:
                hall, meal = place, ""
            if hall not in groups:
                groups[hall] = []
                order.append(hall)
            preference = preference_from_name(item["name"])
            groups[hall].append(
                {
                    "name": item["name"],
                    "meal": meal,
                    "preference": preference["id"] if preference else "",
                    "preference_label": preference["label"] if preference else "",
                    "goals": item.get("goals") or [],
                }
            )
    return [{"hall": hall, "dishes": groups[hall]} for hall in order]
