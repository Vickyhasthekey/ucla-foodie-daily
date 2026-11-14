import os
import tempfile
import unittest


class SignInTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["FOODIE_DATA"] = self._tmpdir.name
        os.environ.pop("DATABASE_URL", None)
        import app.db as db
        import app.service as service

        db._ready_for = None
        self.db = db
        self.service = service
        service.init_db()

    def tearDown(self):
        self.db._ready_for = None
        self._tmpdir.cleanup()

    def test_complete_sign_in_merges_guest_prefs_once(self):
        user = self.service.complete_sign_in(
            "speed@example.com",
            {
                "allergens": ["Eggs"],
                "rules": ["vegetarian"],
                "never": ["beef", "dessert"],
            },
        )
        self.assertEqual(user["email"], "speed@example.com")
        self.assertTrue(user["session_token"])
        restrictions = self.service.get_restrictions(user["id"])
        self.assertEqual(restrictions["allergens"], ["eggs"])
        self.assertEqual(restrictions["rules"], ["vegetarian"])
        never = {row["id"] for row in self.service.list_never(user["id"])}
        self.assertEqual(never, {"beef", "dessert"})

        again = self.service.complete_sign_in("speed@example.com", {"never": ["chicken"]})
        self.assertEqual(again["id"], user["id"])
        never = {row["id"] for row in self.service.list_never(again["id"])}
        self.assertEqual(never, {"beef", "dessert", "chicken"})


if __name__ == "__main__":
    unittest.main()
