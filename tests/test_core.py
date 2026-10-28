import unittest
from pathlib import Path

from app.db import DB_PATH
from app.match import CONCEPTS, accepted_halls, group_by_meal, preference_from_name, preferences_from_wish, recommend
from app.semantic import lexical_scores
from app.menu import boutique_locations, page_matches_date, parse_boutique_html, parse_menu_html

FIXTURE = """
<div id='breakfastmenu'>
  <h3>De Neve Dining</h3>
  <h4>The Grill</h4>
  <ul>  <li><a href='/menu-item/?recipe=1475'>French Toast</a>
  <img class='meal-station__allergen-icon' title='Vegetarian'></li>
  <li><a href='/menu-item/?recipe=99'>Beef Bulgogi</a></li></ul>
  <h3>Bruin Plate</h3>
  <ul><li><a href='/menu-item/?recipe=99'>Beef Bulgogi</a></li></ul>
</div>
<div id='lunchmenu'>
  <h3>De Neve Dining</h3>
  <ul><li><a href='/menu-item/?recipe=7'>Grilled Salmon</a></li>
  <li><a href='/menu-item/?recipe=8'>Scrambled Eggs</a></li>
  <li><a href='/menu-item/?recipe=9'>Eggplant Parmesan</a></li></ul>
</div>
<img title="Fish" alt="Fish">
"""


class MenuTests(unittest.TestCase):
    def test_parse_groups_halls_and_meals(self):
        dishes = parse_menu_html(FIXTURE)
        names = [(d["meal"], d["hall"], d["name"]) for d in dishes]
        self.assertIn(("Breakfast", "De Neve Dining", "French Toast"), names)
        self.assertIn(("Lunch", "De Neve Dining", "Grilled Salmon"), names)
        toast = next(d for d in dishes if d["name"] == "French Toast")
        self.assertEqual(toast["tags"], ["Vegetarian"])
        salmon = next(d for d in dishes if d["name"] == "Grilled Salmon")
        self.assertEqual(salmon["tags"], [])
        self.assertEqual(toast["recipe_id"], "1475")

    def test_free_text_ranks_the_closer_dish(self):
        def fake_scores(query, documents):
            return [0.9 if "beef" in document else 0.4 for document in documents]

        result = recommend(parse_menu_html(FIXTURE), "a warm plate of beef", score_fn=fake_scores)
        names = {item["name"] for item in result["matched"]}
        self.assertIn("Beef Bulgogi", names)
        self.assertNotIn("French Toast", names)
        self.assertNotIn("Eggplant Parmesan", names)
        bulgogi = next(item for item in result["matched"] if item["name"] == "Beef Bulgogi")
        self.assertEqual(len(bulgogi["places"]), 2)

    def test_steak_saves_as_beef_and_similar_words(self):
        pref = preference_from_name("Grilled Honey Balsamic Flank Steak")
        self.assertEqual(pref["id"], "beef")
        self.assertEqual(pref["label"], "Beef")
        self.assertIn("beef", pref["words"])
        self.assertIn("steak", pref["words"])
        self.assertIn("bulgogi", pref["words"])

    def test_wish_save_is_one_preference_not_each_dish(self):
        prefs = preferences_from_wish("beef, salmon, tiramisu")
        self.assertEqual([item["id"] for item in prefs], ["beef", "fish", "dessert"])

    def test_matches_are_grouped_breakfast_then_lunch_then_dinner(self):
        def fake_scores(query, documents):
            return [0.9 if "beef" in document else 0.4 for document in documents]

        matched = recommend(parse_menu_html(FIXTURE), "beef", score_fn=fake_scores)["matched"]
        meals = group_by_meal(matched)
        self.assertEqual(
            [meal["meal"] for meal in meals],
            ["Breakfast", "Lunch", "Dinner", "All day"],
        )
        breakfast_halls = {hall["hall"] for hall in meals[0]["halls"]}
        self.assertEqual(breakfast_halls, {"De Neve Dining", "Bruin Plate"})
        self.assertEqual(meals[1]["halls"], [])
        self.assertEqual(meals[2]["halls"], [])
        self.assertEqual(meals[3]["halls"], [])

    def test_boutique_page_reads_all_day_dishes(self):
        html = """
        <h2>Today's Hours</h2>
        <div id='alldaymenu'>
          <h2>All Day</h2>
          <h2>Tartines</h2>
          <div class='menu-item-title'><h3>Croque Monsieur</h3></div>
          <a href='/menu-item/?recipe=1539'>See Meal Details</a>
          <div class='menu-item-title'><h3>Belgian Waffle</h3></div>
          <a href='/menu-item/?recipe=200'>See Meal Details</a>
        </div>
        """
        dishes = parse_boutique_html(html, "The Study at Hedrick")
        self.assertEqual(
            [(dish["meal"], dish["hall"], dish["station"], dish["name"], dish["recipe_id"]) for dish in dishes],
            [
                ("All day", "The Study at Hedrick", "Tartines", "Croque Monsieur", "1539"),
                ("All day", "The Study at Hedrick", "Tartines", "Belgian Waffle", "200"),
            ],
        )
        self.assertTrue(page_matches_date("Today, October 11, 2026", "2026-10-11"))
        self.assertFalse(page_matches_date("<option>October 11, 2026</option>", "2026-10-11"))

    def test_boutique_list_skips_food_trucks_and_residential_halls(self):
        html = """
        <article class='ucla-tabpanel'>
          <a href='/bruin-plate/'>Bruin Plate</a>
        </article>
        <article class='ucla-tabpanel' hidden>
          <a href='/the-study-at-hedrick/'>The Study at Hedrick</a>
          <span class='open'>Open</span>
          <a href='/meal-swipe-exchange/'>Food Trucks &amp; Restaurants</a>
          <a href='/rendezvous/'>Rendezvous</a>
          <a href='/bruin-bowl/'>Bruin Bowl</a>
          <span class='closed'>Closed</span>
        </article>
        <article class='ucla-tabpanel' hidden>
          <a href='/hours/'>Hours</a>
        </article>
        """
        places = boutique_locations(html)
        self.assertEqual(
            places,
            [
                {"name": "The Study at Hedrick", "url": "https://dining.ucla.edu/the-study-at-hedrick/"},
                {"name": "Rendezvous", "url": "https://dining.ucla.edu/rendezvous/"},
            ],
        )

    def test_plan_keeps_only_halls_offered_for_that_meal(self):
        meals = [
            {"meal": "Breakfast", "halls": [{"hall": "De Neve Dining"}]},
            {"meal": "Lunch", "halls": [{"hall": "Bruin Plate"}]},
            {"meal": "Dinner", "halls": []},
        ]
        kept = accepted_halls(
            meals,
            {"Breakfast": "De Neve Dining", "Lunch": "Epicuria at Covel", "Dinner": "Bruin Plate"},
        )
        self.assertEqual(kept, {"Breakfast": ["De Neve Dining"]})

    def test_all_day_can_keep_more_than_one_place(self):
        meals = [
            {"meal": "Breakfast", "halls": [{"hall": "De Neve Dining"}]},
            {"meal": "All day", "halls": [{"hall": "The Study at Hedrick"}, {"hall": "Rendezvous"}]},
        ]
        kept = accepted_halls(
            meals,
            {
                "Breakfast": ["De Neve Dining", "Bruin Plate"],
                "All day": ["The Study at Hedrick", "Rendezvous", "The Drey"],
            },
        )
        self.assertEqual(
            kept,
            {
                "Breakfast": ["De Neve Dining"],
                "All day": ["The Study at Hedrick", "Rendezvous"],
            },
        )

    def test_food_words_pick_the_matching_concept_without_a_model(self):
        texts = [concept["text"] for concept in CONCEPTS]
        scores = lexical_scores("beef", texts)
        self.assertEqual(CONCEPTS[scores.index(max(scores))]["id"], "beef")
        scores = lexical_scores("tiramisu", texts)
        self.assertEqual(CONCEPTS[scores.index(max(scores))]["id"], "dessert")


class LivePageTests(unittest.TestCase):
    def test_saved_page_has_dishes(self):
        path = Path("/tmp/ucla-menu.html")
        if not path.exists():
            self.skipTest("no saved menu page")
        dishes = parse_menu_html(path.read_text(errors="replace"))
        self.assertGreater(len(dishes), 20)
        self.assertTrue(any(d["hall"] == "Bruin Plate" for d in dishes))


class DbIsolation(unittest.TestCase):
    def test_database_path_is_inside_the_repo(self):
        self.assertEqual(DB_PATH.name, "foodie.db")


if __name__ == "__main__":
    unittest.main()
