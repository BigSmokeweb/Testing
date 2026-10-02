import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models import User, Site, engine
from app.auth import create_session_token, SESSION_COOKIE_NAME, hash_password


class TestSitesVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suffix = uuid.uuid4().hex[:6]
        with Session(engine) as session:
            u1 = User(email=f"u1_{suffix}@example.com", password_hash=hash_password("pw123456"), email_verified=True)
            session.add(u1)
            u2 = User(email=f"u2_{suffix}@example.com", password_hash=hash_password("pw123456"), email_verified=True)
            session.add(u2)
            session.commit()
            session.refresh(u1)
            session.refresh(u2)
            cls.user1_id = u1.id
            cls.user2_id = u2.id

        cls.user1_token = create_session_token(cls.user1_id)
        cls.user2_token = create_session_token(cls.user2_id)

    def test_add_site_and_isolation(self):
        c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: self.user1_token})
        c2 = TestClient(app, cookies={SESSION_COOKIE_NAME: self.user2_token})

        res = c1.get("/sites")
        self.assertEqual(res.status_code, 200)

        import re
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
        self.assertIsNotNone(match)
        csrf = match.group(1)

        domain = f"test-{uuid.uuid4().hex[:6]}.com"
        res = c1.post(
            "/sites",
            data={"url": f"https://{domain}", "csrf_token": csrf},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn(domain, res.text)

        # User 2 does not see user 1's domain
        res2 = c2.get("/sites")
        self.assertEqual(res2.status_code, 200)
        self.assertNotIn(domain, res2.text)

    def test_verify_fail_then_pass_mocked(self):
        c1 = TestClient(app, cookies={SESSION_COOKIE_NAME: self.user1_token})
        res = c1.get("/sites")
        import re
        csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text).group(1)

        domain = f"verify-{uuid.uuid4().hex[:6]}.com"
        c1.post("/sites", data={"url": f"https://{domain}", "csrf_token": csrf}, follow_redirects=True)

        with Session(engine) as session:
            site = session.exec(select(Site).where(Site.domain == domain)).first()
            self.assertIsNotNone(site)
            site_id = site.id

        # 1. Verification fails when no DNS or file exists
        with patch("app.sites.check_dns_txt_record", return_value=False), \
             patch("app.sites.check_well_known_file", return_value=False):
            res_fail = c1.post(
                f"/sites/{site_id}/verify",
                data={"csrf_token": csrf},
                follow_redirects=True,
            )
            self.assertEqual(res_fail.status_code, 200)
            self.assertIn("Verification failed", res_fail.text)

        # 2. Verification succeeds when file returns token
        with patch("app.sites.check_dns_txt_record", return_value=False), \
             patch("app.sites.check_well_known_file", return_value=True):
            res_pass = c1.post(
                f"/sites/{site_id}/verify",
                data={"csrf_token": csrf},
                follow_redirects=True,
            )
            self.assertEqual(res_pass.status_code, 200)
            self.assertIn("Verified", res_pass.text)


if __name__ == "__main__":
    unittest.main()
