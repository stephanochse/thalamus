import unittest

from _helpers import temp_home
from thalamus.scrub import scrub


class ScrubTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(self)

    def test_emails(self):
        r = scrub("write to jane.doe@example.com today")
        self.assertEqual(r.text, "write to [email] today")
        self.assertEqual(r.counts["emails"], 1)

    def test_keep_emails(self):
        self.assertIn("a@b.io", scrub("mail a@b.io", keep_emails=True).text)

    def test_api_keys(self):
        text = ("openai sk-abcdefghijklmnop1234 anthropic sk-ant-api03-abcdefghijklmnop "
                "openrouter sk-or-v1-abcdefghijklmnop1234 gh ghp_abcdefghijklmnopqrstuv "
                "aws " + "AKIA" + "ABCDEFGHIJKLMNOP" + " google AIza" + "A" * 35 + " slack xoxb-1234567890-abcdef")
        r = scrub(text)
        for leaked in ("sk-abc", "sk-ant", "sk-or-v1", "ghp_", "AKIA", "AIza", "xoxb"):
            self.assertNotIn(leaked, r.text)
        self.assertEqual(r.counts["secrets"], 7)

    def test_jwt_and_bearer(self):
        jwt = ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0", "abcdefghijklmnop"])
        r = scrub(f"token {jwt} and Authorization: Bearer abcdefghijklmnopqrstuvwx")
        self.assertNotIn("eyJ", r.text)
        self.assertNotIn("abcdefghijklmnopqrstuvwx", r.text)

    def test_keyed_secret_keeps_key(self):
        fake = "Zx9fK3mQp7" + "Lw2Rt8Vb5Nc"  # built at runtime so secret scanners don't flag the fixture
        r = scrub("config: api_" + f"key = '{fake}' and password: hunter2hunter2hunter2")
        self.assertIn("api_key", r.text)
        self.assertNotIn(fake, r.text)
        self.assertNotIn("hunter2hunter2hunter2", r.text)

    def test_phone_numbers_but_not_dates(self):
        r = scrub("call +44 20 7946 0958 or (415) 555-2671, filed 2026-11-02, v1.2.3, order 12345")
        self.assertEqual(r.counts["phones"], 2)
        self.assertIn("2026-11-02", r.text)
        self.assertIn("order 12345", r.text)

    def test_private_terms(self):
        (self.home / "private-terms.txt").write_text("# comment\nAcme Corp\nAcme\nZed\n", encoding="utf-8")
        r = scrub("ACME CORP and acme, plus zed. Zedra is fine.")
        self.assertNotIn("acme", r.text.lower())
        self.assertIn("Zedra", r.text)
        self.assertEqual(r.counts["names"], 3)
        self.assertEqual(set(r.names.values()), {"Acme Corp", "Acme", "Zed"})
        again = scrub("acme corp")
        self.assertEqual(again.text, [k for k, v in r.names.items() if v == "Acme Corp"][0])

    def test_no_terms_file(self):
        r = scrub("plain text")
        self.assertEqual((r.text, r.names), ("plain text", {}))


if __name__ == "__main__":
    unittest.main()
