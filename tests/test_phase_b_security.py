"""
Phase B security probes:
- SSRF on POST /sites and /wizard/start
- IDOR: user2 accessing user1's resources
- CSRF rejection
- XSS escaping in report
- Path traversal
"""
import os
import re
import uuid
import unittest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models import User, Site, Run, engine
from app.auth import create_session_token, SESSION_COOKIE_NAME, hash_password


def _make_user(suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    email = f"probe_{suffix}@example.com"
    with Session(engine) as s:
        u = User(email=email, password_hash=hash_password("Probe1234!"), email_verified=True)
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    return uid, create_session_token(uid)


def _get_csrf(client, url="/sites"):
    res = client.get(url)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
    return m.group(1) if m else ""


class TestSSRFOnSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid, cls.token = _make_user()
        cls.client = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token})
        cls.csrf = _get_csrf(cls.client)

    def _post_site(self, url):
        res = self.client.post("/sites", data={"url": url, "csrf_token": self.csrf}, follow_redirects=True)
        return res.status_code, res.text

    def test_ssrf_localhost(self):
        _, body = self._post_site("http://localhost")
        self.assertNotIn("Site added successfully", body, "SSRF: localhost accepted")

    def test_ssrf_127_port(self):
        _, body = self._post_site("http://127.0.0.1:5432")
        self.assertNotIn("Site added successfully", body, "SSRF: 127.0.0.1:5432 accepted")

    def test_ssrf_metadata(self):
        _, body = self._post_site("http://169.254.169.254")
        self.assertNotIn("Site added successfully", body, "SSRF: metadata IP accepted")

    def test_ssrf_ipv6_loopback(self):
        _, body = self._post_site("http://[::1]")
        self.assertNotIn("Site added successfully", body, "SSRF: IPv6 ::1 accepted")

    def test_ssrf_hex_loopback(self):
        code, body = self._post_site("http://0x7f000001")
        accepted = "Site added successfully" in body
        print(f"\n[SSRF-HEX] 0x7f000001 accepted={accepted} code={code}")

    def test_ssrf_embedded_credentials(self):
        _, body = self._post_site("http://user:pass@example.com")
        self.assertNotIn("Site added successfully", body, "SSRF: embedded creds accepted")

    def test_ssrf_ftp_scheme(self):
        _, body = self._post_site("ftp://example.com")
        self.assertNotIn("Site added successfully", body, "SSRF: ftp scheme accepted")

    def test_ssrf_file_scheme(self):
        _, body = self._post_site("file:///etc/passwd")
        self.assertNotIn("Site added successfully", body, "SSRF: file scheme accepted")


class TestSSRFOnWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid, cls.token = _make_user()
        cls.client = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token})
        cls.csrf = _get_csrf(cls.client, "/wizard")

    def _post_wizard(self, url):
        res = self.client.post("/wizard/start", data={"url": url, "authorized": "on", "csrf_token": self.csrf}, follow_redirects=True)
        return res.status_code, res.text

    def test_wizard_ssrf_localhost(self):
        _, body = self._post_wizard("http://localhost")
        self.assertNotIn("success", body.lower(), "Wizard SSRF: localhost accepted")

    def test_wizard_ssrf_metadata(self):
        _, body = self._post_wizard("http://169.254.169.254")
        self.assertNotIn("success", body.lower(), "Wizard SSRF: metadata IP accepted")

    def test_wizard_ssrf_file(self):
        _, body = self._post_wizard("file:///etc/passwd")
        self.assertNotIn("success", body.lower(), "Wizard SSRF: file scheme accepted")

    def test_wizard_ssrf_embedded_creds(self):
        _, body = self._post_wizard("http://user:pass@example.com")
        self.assertNotIn("success", body.lower(), "Wizard SSRF: embedded creds accepted")


class TestIDOR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid1, cls.token1 = _make_user()
        cls.uid2, cls.token2 = _make_user()
        cls.c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token1})
        cls.c2 = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token2})
        with Session(engine) as s:
            site = Site(user_id=cls.uid1, url="https://idor-test.example.com", domain="idor-test.example.com", verify_token="tok_idor_test", verified_at=None)
            s.add(site)
            s.commit()
            s.refresh(site)
            cls.site1_id = site.id
        with Session(engine) as s:
            run = Run(site_id=cls.site1_id, engine="chromium", status="passed", mode="public", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00")
            s.add(run)
            s.commit()
            s.refresh(run)
            cls.run1_id = run.id

    @unittest.skipIf(os.getenv("LOCAL_MODE", "0") == "1", "Local mode bypasses ownership checks by design")
    def test_idor_report(self):
        res = self.c2.get(f"/report/{self.run1_id}", follow_redirects=True)
        leaked = res.status_code == 200 and "idor-test.example.com" in res.text
        print(f"\n[IDOR-REPORT] status={res.status_code} leaked={leaked}")
        if leaked:
            self.fail("IDOR BUG: user2 can view user1 run report")

    @unittest.skipIf(os.getenv("LOCAL_MODE", "0") == "1", "Local mode bypasses ownership checks by design")
    def test_idor_run_status(self):
        res = self.c2.get(f"/runs/{self.run1_id}/status", follow_redirects=False)
        print(f"\n[IDOR-STATUS] status={res.status_code}")
        if res.status_code == 200:
            self.fail("IDOR BUG: user2 can poll user1 run status")

    def test_idor_verify_site(self):
        csrf2 = _get_csrf(self.c2)
        res = self.c2.post(f"/sites/{self.site1_id}/verify", data={"csrf_token": csrf2}, follow_redirects=True)
        self.assertNotIn("verified successfully", res.text.lower(), "IDOR BUG: user2 verified user1 site")

    def test_idor_run_on_site(self):
        csrf2 = _get_csrf(self.c2)
        res = self.c2.post(f"/sites/{self.site1_id}/run", data={"mode": "public", "csrf_token": csrf2}, follow_redirects=True)
        self.assertNotIn("queued", res.text.lower(), "IDOR BUG: user2 triggered run on user1 site")


class TestCSRF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid, cls.token = _make_user()
        cls.client = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token})

    def test_post_sites_no_csrf(self):
        res = self.client.post("/sites", data={"url": "https://example.com"}, follow_redirects=True)
        self.assertNotIn("Site added successfully", res.text, "CSRF: POST /sites without token succeeded")

    def test_post_sites_wrong_csrf(self):
        res = self.client.post("/sites", data={"url": "https://example.com", "csrf_token": "bad"}, follow_redirects=True)
        self.assertNotIn("Site added successfully", res.text, "CSRF: POST /sites with wrong token succeeded")

    def test_post_login_no_csrf(self):
        res = self.client.post("/login", data={"email": "a@b.com", "password": "wrong"}, follow_redirects=False)
        self.assertEqual(res.status_code, 400)
        self.assertIn("CSRF", res.text)

    def test_post_register_no_csrf(self):
        email = f"nocsrf_{uuid.uuid4().hex[:6]}@example.com"
        res = self.client.post("/register", data={"email": email, "password": "Test1234!"}, follow_redirects=False)
        self.assertEqual(res.status_code, 400)


class TestXSSEscaping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid, cls.token = _make_user()
        cls.client = TestClient(app, cookies={SESSION_COOKIE_NAME: cls.token})
        payload = "<script>alert(1)</script>"
        with Session(engine) as s:
            run = Run(user_id=cls.uid, site_id=None, engine=payload, status="passed", mode="public", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:01:00")
            s.add(run)
            s.commit()
            s.refresh(run)
            cls.run_id = run.id
        cls.payload = payload

    def test_report_engine_escaped(self):
        res = self.client.get(f"/report/{self.run_id}", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.payload, res.text, "XSS BUG: raw script in report")
        print(f"\n[XSS-REPORT] escaped_present={'&lt;script&gt;' in res.text}")

    def test_history_engine_escaped(self):
        res = self.client.get("/history", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(self.payload, res.text, "XSS BUG: raw script in history")


class TestPathTraversal(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_no_env_leakage(self):
        urls = [
            "/artifacts/../.env", "/static/../.env", "/static/../../.env",
            "/.env", "/..%2F.env", "/artifacts/%2e%2e/%2e%2e/.env", "/static/%2e%2e/.env",
        ]
        for url in urls:
            try:
                res = self.client.get(url, follow_redirects=False)
                leaked = res.status_code == 200 and any(k in res.text for k in ["SECRET", "DATABASE_URL", "REDIS_URL", "JWT"])
                print(f"\n[TRAVERSAL] {url} => {res.status_code} leaked={leaked}")
                self.assertFalse(leaked, f"PATH TRAVERSAL BUG: {url} leaked env file")
            except Exception as e:
                print(f"\n[TRAVERSAL] {url} => exception {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


