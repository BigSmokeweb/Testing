import unittest
from fastapi.testclient import TestClient
from app.main import app


class TestSecurityHeadersAndPages(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_security_headers_present_on_all_pages(self):
        pages = [
            "/",
            "/login",
            "/register",
            "/wizard",
            "/sites",
            "/history",
            "/terms",
            "/privacy",
            "/robots.txt",
        ]
        for path in pages:
            resp = self.client.get(path, follow_redirects=True)
            self.assertEqual(resp.headers.get("referrer-policy"), "no-referrer", f"Failed on {path}")
            self.assertEqual(resp.headers.get("x-robots-tag"), "noindex, nofollow", f"Failed on {path}")
            self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff", f"Failed on {path}")
            self.assertEqual(resp.headers.get("x-frame-options"), "DENY", f"Failed on {path}")
            self.assertIn("default-src 'self'", resp.headers.get("content-security-policy", ""), f"Failed on {path}")

    def test_robots_txt_disallows_all(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Disallow: /", resp.text)

    def test_privacy_page_content(self):
        resp = self.client.get("/privacy")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Privacy Policy", resp.text)
