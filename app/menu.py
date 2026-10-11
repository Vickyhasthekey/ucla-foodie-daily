import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import ssl

MENU_URL = "https://dining.ucla.edu/menus-at-a-glance/?date={date}"
LOCATIONS_URL = "https://dining.ucla.edu/dining-locations/"
ALL_DAY = "All day"
MEAL_IDS = {
    "breakfastmenu": "Breakfast",
    "lunchmenu": "Lunch",
    "dinnermenu": "Dinner",
}


class _MenuParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meal = None
        self.hall = None
        self.station = ""
        self.dishes = []
        self._capture = None
        self._buf = []
        self._href = ""
        self._current = None

    def handle_starttag(self, tag, attrs):
        data = {key: value or "" for key, value in attrs}
        element_id = data.get("id", "")
        if element_id in MEAL_IDS:
            self.meal = MEAL_IDS[element_id]
            self.hall = None
            self.station = ""
            self._finish_dish()
        if tag in ("h3", "h4") and self.meal:
            self._finish_dish()
            self._capture = tag
            self._buf = []
        if tag == "a" and self.meal and self.hall and "recipe=" in data.get("href", ""):
            self._finish_dish()
            self._capture = "dish"
            self._href = data.get("href", "")
            self._buf = []
        if (
            tag == "img"
            and self._current is not None
            and "meal-station__allergen-icon" in data.get("class", "")
            and data.get("title")
        ):
            title = data["title"].strip()
            if title and title not in self._current["tags"]:
                self._current["tags"].append(title)

    def handle_endtag(self, tag):
        if self._capture in ("h3", "h4") and tag == self._capture:
            text = self._text()
            if self._capture == "h3":
                self.hall = text
                self.station = ""
            else:
                self.station = text
            self._capture = None
        elif self._capture == "dish" and tag == "a":
            name = self._text()
            recipe = ""
            match = re.search(r"recipe=(\d+)", self._href)
            if match:
                recipe = match.group(1)
            if name and self.hall:
                self._current = {
                    "meal": self.meal,
                    "hall": self.hall,
                    "station": self.station,
                    "name": name,
                    "recipe_id": recipe,
                    "tags": [],
                }
            self._capture = None
            self._href = ""

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)

    def _text(self):
        return re.sub(r"\s+", " ", "".join(self._buf)).strip()

    def _finish_dish(self):
        if self._current:
            self.dishes.append(self._current)
            self._current = None

    def close(self):
        super().close()
        self._finish_dish()


def parse_menu_html(html):
    parser = _MenuParser()
    parser.feed(html)
    parser.close()
    return parser.dishes


def fetch_html(url):
    request = Request(url, headers={"User-Agent": "ucla-foodie-daily"})
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=30, context=context) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        # The system Python on this machine sometimes lacks CA certs. curl uses the OS store.
        import subprocess

        result = subprocess.run(
            ["curl", "-fsSL", "--max-time", "30", "-A", "ucla-foodie-daily", url],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", "replace")


def fetch_menu_html(menu_date):
    return fetch_html(MENU_URL.format(date=menu_date))


def _absolute(href):
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if not href.startswith("/"):
        href = "/" + href
    return "https://dining.ucla.edu" + href


class _BoutiqueListParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.places = []
        self._panel = None
        self._depth = 0
        self._finished = False
        self._capture = False
        self._href = ""
        self._buf = []

    def handle_starttag(self, tag, attrs):
        data = {key: value or "" for key, value in attrs}
        if tag == "article" and "ucla-tabpanel" in data.get("class", ""):
            if self._finished:
                return
            self._panel = "hidden" in data
            self._depth = 1
            return
        if self._panel and tag == "article":
            self._depth += 1
        if self._panel and tag == "a":
            self._capture = True
            self._href = data.get("href", "")
            self._buf = []

    def handle_endtag(self, tag):
        if self._capture and tag == "a":
            name = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            href = self._href
            if name and href and "meal-swipe" not in href and not href.startswith("#"):
                self.places.append({"name": name, "url": _absolute(href)})
            self._capture = False
            self._buf = []
            self._href = ""
        if self._panel is not None and tag == "article":
            self._depth -= 1
            if self._depth <= 0:
                if self._panel:
                    self._finished = True
                self._panel = None

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def boutique_locations(html):
    parser = _BoutiqueListParser()
    parser.feed(html)
    parser.close()
    seen = set()
    places = []
    for place in parser.places:
        if place["url"] in seen:
            continue
        seen.add(place["url"])
        places.append(place)
    return places


def page_matches_date(html, menu_date):
    day = datetime.strptime(menu_date, "%Y-%m-%d")
    label = f"Today, {day.strftime('%B')} {day.day}, {day.year}"
    return label in html


class _BoutiqueMenuParser(HTMLParser):
    def __init__(self, hall):
        super().__init__(convert_charrefs=True)
        self.hall = hall
        self.station = ""
        self._in_menu = False
        self.dishes = []
        self._in_title = False
        self._title_depth = 0
        self._capture = None
        self._buf = []
        self._pending = None

    def handle_starttag(self, tag, attrs):
        data = {key: value or "" for key, value in attrs}
        if data.get("id") == "alldaymenu":
            self._in_menu = True
        if tag == "h2":
            self._capture = "h2"
            self._buf = []
        if tag == "div" and "menu-item-title" in data.get("class", ""):
            self._in_title = True
            self._title_depth = 1
        elif self._in_title and tag == "div":
            self._title_depth += 1
        if tag == "h3" and self._in_title:
            self._capture = "dish"
            self._buf = []
        if tag == "a" and self._pending and "recipe=" in data.get("href", ""):
            match = re.search(r"recipe=(\d+)", data.get("href", ""))
            if match:
                self._pending["recipe_id"] = match.group(1)
            self._keep_pending()

    def handle_endtag(self, tag):
        if self._capture == "h2" and tag == "h2":
            text = self._text()
            if text.lower() == "all day":
                self._in_menu = True
                self.station = ""
            elif text and self._in_menu:
                self.station = text
            self._capture = None
        elif self._capture == "dish" and tag == "h3":
            name = self._text()
            self._keep_pending()
            if name and self._in_menu:
                self._pending = {
                    "meal": ALL_DAY,
                    "hall": self.hall,
                    "station": self.station,
                    "name": name,
                    "recipe_id": "",
                    "tags": [],
                }
            self._capture = None
        if self._in_title and tag == "div":
            self._title_depth -= 1
            if self._title_depth <= 0:
                self._in_title = False

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)

    def _text(self):
        return re.sub(r"\s+", " ", "".join(self._buf)).strip()

    def _keep_pending(self):
        if self._pending:
            self.dishes.append(self._pending)
            self._pending = None

    def close(self):
        super().close()
        self._keep_pending()


def parse_boutique_html(html, hall):
    parser = _BoutiqueMenuParser(hall)
    parser.feed(html)
    parser.close()
    return parser.dishes


def _dishes_for_place(menu_date, place):
    try:
        page = fetch_html(place["url"])
    except Exception:
        return []
    if not page_matches_date(page, menu_date):
        return []
    return parse_boutique_html(page, place["name"])


def fetch_boutique_dishes(menu_date):
    places = boutique_locations(fetch_html(LOCATIONS_URL))
    dishes = []
    if not places:
        return dishes
    with ThreadPoolExecutor(max_workers=min(6, len(places))) as pool:
        batches = pool.map(lambda place: _dishes_for_place(menu_date, place), places)
        for batch in batches:
            dishes.extend(batch)
    return dishes


def menu_lines(dishes):
    lines = []
    for dish in dishes:
        lines.append(f"{dish['hall']} | {dish['meal']} | {dish['name']}")
    return "\n".join(lines)
