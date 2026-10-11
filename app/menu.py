import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import ssl

MENU_URL = "https://dining.ucla.edu/menus-at-a-glance/?date={date}"
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


def fetch_menu_html(menu_date):
    url = MENU_URL.format(date=menu_date)
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


def menu_lines(dishes):
    lines = []
    for dish in dishes:
        lines.append(f"{dish['hall']} | {dish['meal']} | {dish['name']}")
    return "\n".join(lines)
