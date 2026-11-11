import unittest

from app.game import (
    LIKE_TARGET,
    apply_swipe,
    build_deck,
    empty_session,
    filter_dishes,
    match_result,
)


MENU = [
    {"meal": "Lunch", "hall": "Bruin Plate", "name": "Beef Barley Soup", "tags": [], "station": "", "recipe_id": ""},
    {"meal": "Lunch", "hall": "De Neve Dining", "name": "Midwest Pepper Steak", "tags": [], "station": "", "recipe_id": ""},
    {"meal": "Dinner", "hall": "Bruin Plate", "name": "Grilled Salmon", "tags": ["Contains Fish"], "station": "", "recipe_id": ""},
    {"meal": "Dinner", "hall": "De Neve Dining", "name": "Chicken Tenders", "tags": [], "station": "", "recipe_id": ""},
    {"meal": "All day", "hall": "Rendezvous", "name": "BBQ Beef Brisket Sandwich", "tags": [], "station": "", "recipe_id": ""},
    {"meal": "All day", "hall": "The Study at Hedrick", "name": "Tiramisu", "tags": ["Contains Dairy"], "station": "", "recipe_id": ""},
]


class GameTests(unittest.TestCase):
    def test_restrictions_drop_blocked_dishes(self):
        kept = filter_dishes(
            MENU,
            {"allergens": ["fish"], "rules": ["no_chicken"]},
            never_ids=["dessert"],
        )
        names = {dish["name"] for dish in kept}
        self.assertIn("Beef Barley Soup", names)
        self.assertNotIn("Grilled Salmon", names)
        self.assertNotIn("Chicken Tenders", names)
        self.assertNotIn("Tiramisu", names)

    def test_deck_mixes_close_and_popular(self):
        deck = build_deck(MENU, ["beef"], [], {"allergens": [], "rules": []})
        self.assertTrue(deck)
        self.assertLessEqual(len(deck), 12)
        self.assertTrue(any("Beef" in dish["name"] or "Steak" in dish["name"] or "Brisket" in dish["name"] for dish in deck))

    def test_optional_meal_filter_limits_the_deck(self):
        deck = build_deck(
            MENU,
            [],
            [],
            {"allergens": [], "rules": [], "meals": ["All day"]},
        )
        self.assertTrue(deck)
        self.assertTrue(all(dish["meal"] == "All day" for dish in deck))

    def test_deck_spreads_across_dining_spots(self):
        wide = MENU + [
            {"meal": "Lunch", "hall": "Epicuria at Covel", "name": "Lemon Herb Chicken", "tags": [], "station": "", "recipe_id": ""},
            {"meal": "Dinner", "hall": "Feast at Rieber", "name": "Beef Pho Noodle Soup", "tags": [], "station": "", "recipe_id": ""},
            {"meal": "All day", "hall": "Bruin Café", "name": "Ham & Swiss Sandwich", "tags": [], "station": "", "recipe_id": ""},
        ]
        deck = build_deck(wide, ["beef"], [], {"allergens": [], "rules": []})
        halls = {dish["hall"] for dish in deck}
        self.assertGreaterEqual(len(halls), 4)
        self.assertLess(max(sum(1 for dish in deck if dish["hall"] == hall) for hall in halls), 4)

    def test_three_likes_ends_the_game(self):
        session = empty_session(["a|a|A", "b|b|B", "c|c|C", "d|d|D"])
        session, done = apply_swipe(session, "like")
        self.assertFalse(done)
        session, done = apply_swipe(session, "like")
        self.assertFalse(done)
        session, done = apply_swipe(session, "like")
        self.assertTrue(done)
        self.assertEqual(len(session["likes"]), LIKE_TARGET)

    def test_undo_restores_last_card(self):
        session = empty_session(["a|a|A", "b|b|B"])
        session, _ = apply_swipe(session, "pass")
        self.assertEqual(session["index"], 1)
        session, _ = apply_swipe(session, "undo")
        self.assertEqual(session["index"], 0)
        self.assertEqual(session["passes"], [])

    def test_result_suggests_a_hall_per_meal(self):
        liked = [MENU[0], MENU[4]]
        meals, suggestions = match_result(liked, MENU, {"allergens": [], "rules": []}, [], [], [])
        self.assertEqual([meal["meal"] for meal in meals], ["Breakfast", "Lunch", "Dinner", "All day"])
        self.assertIn("Lunch", suggestions)
        self.assertTrue(any(meal["halls"] for meal in meals))


if __name__ == "__main__":
    unittest.main()
