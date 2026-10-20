import os
import re
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models import User, Site, engine
from app.auth import (
    create_session_token,
    hash_password,
    SESSION_COOKIE_NAME,
    WIZARD_URL_COOKIE_NAME,
    create_wizard_url_token,
)


def _get_csrf(client, url="/register"):
    res = client.get(url)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
    return m.group(1) if m else ""


class TestWizardPrivacy(unittest.TestCase):
    def setUp(self):
        with Session(engine) as session:
            u1 = User(email=f"user1_{os.urandom(4).hex()}@example.com", password_hash=hash_password("pw123"))
            u2 = User(email=f"user2_{os.urandom(4).hex()}@example.com", password_hash=hash_password("pw123"))
            session.add(u1)
            session.add(u2)
            session.commit()
            session.refresh(u1)
            session.refresh(u2)
            self.u1_id = u1.id
            self.u2_id = u2.id
            self.u1_email = u1.email
            self.u2_email = u2.email

            s1 = Site(user_id=u1.id, url="https://cust-secret-site.com", domain="cust-secret-site.com", verify_token="tok1")
            session.add(s1)
            session.commit()
            session.refresh(s1)
            self.s1_id = s1.id

        self.tok1 = create_session_token(self.u1_id)
        self.tok2 = create_session_token(self.u2_id)
        self.client1 = TestClient(app, cookies={SESSION_COOKIE_NAME: self.tok1})
        self.client2 = TestClient(app, cookies={SESSION_COOKIE_NAME: self.tok2})
        self.anon_client = TestClient(app)

    @patch("app.sites.validate_url", return_value=(True, ""))
    def test_wizard_url_param_not_in_redirect_for_logged_in(self, mock_val):
        csrf = _get_csrf(self.client1, "/wizard")
        resp = self.client1.post("/wizard/start", data={"url": "https://cust-secret-site.com", "csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        loc = resp.headers.get("location", "")
        self.assertNotIn("cust-secret-site.com", loc)
        self.assertNotIn("url=", loc)
        self.assertIn("site=", loc)

    def test_wizard_url_for_anon_stored_in_cookie_not_url(self):
        csrf = _get_csrf(self.anon_client, "/")
        resp = self.anon_client.post("/wizard/start", data={"url": "https://cust-secret-site.com", "csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        loc = resp.headers.get("location", "")
        self.assertNotIn("cust-secret-site.com", loc)
        self.assertNotIn("url=", loc)
        self.assertEqual(loc, "/register")
        self.assertIn(WIZARD_URL_COOKIE_NAME, resp.cookies)

    def test_wizard_cross_user_site_access_returns_404(self):
        # User 2 tries to access user 1's site in wizard
        resp = self.client2.get(f"/wizard?site={self.s1_id}")
        self.assertEqual(resp.status_code, 404)

    @patch("app.sites.validate_url", return_value=(True, ""))
    def test_register_claims_cookie_url_and_clears_cookie(self, mock_val):
        c = TestClient(app)
        # Get valid CSRF for anon session
        csrf = _get_csrf(c, "/register")
        # Set cookie as if anon visitor posted url
        c.cookies.set(WIZARD_URL_COOKIE_NAME, create_wizard_url_token("https://pending-claim-site.com"))
        
        reg_email = f"claimed_{os.urandom(4).hex()}@example.com"
        resp = c.post(
            "/register",
            data={"email": reg_email, "password": "Password123!", "confirm_password": "Password123!", "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        loc = resp.headers.get("location", "")
        self.assertNotIn("pending-claim-site.com", loc)
        self.assertIn("/wizard?site=", loc)
        # Cookie cleared / set to empty or expired
        cookie_header = resp.headers.get("set-cookie", "")
        self.assertIn(WIZARD_URL_COOKIE_NAME, cookie_header)
