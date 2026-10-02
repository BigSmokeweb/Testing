import unittest
import re
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models import User, engine
from app.auth import SESSION_COOKIE_NAME

client = TestClient(app)


class TestAuthFlow(unittest.TestCase):
    def test_auth_flow(self):
        # 1. Unauthenticated history redirects
        res = client.get("/history", follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertIn("/login", res.headers["location"])

        # 2. Register page contains csrf
        res = client.get("/register")
        self.assertEqual(res.status_code, 200)
        self.assertIn("csrf_token", res.text)

        # Extract csrf token
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text)
        self.assertIsNotNone(match)
        csrf = match.group(1)

        # 3. Register user
        email = "testuser@example.com"
        reg_res = client.post("/register", data={"email": email, "password": "password123", "csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(reg_res.status_code, 303)
        cookie = reg_res.cookies.get(SESSION_COOKIE_NAME)
        self.assertIsNotNone(cookie)

        # Check argon2 password hash in DB
        with Session(engine) as session:
            u = session.exec(select(User).where(User.email == email)).first()
            self.assertIsNotNone(u)
            self.assertTrue(u.password_hash.startswith("$argon2"))

        # 4. History accessible with session cookie
        hist_res = client.get("/history", cookies={SESSION_COOKIE_NAME: cookie})
        self.assertEqual(hist_res.status_code, 200)

        # 5. Wrong login credentials gives generic error
        login_page = client.get("/login")
        login_csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', login_page.text).group(1)
        bad_login = client.post("/login", data={"email": email, "password": "wrongpassword", "csrf_token": login_csrf})
        self.assertEqual(bad_login.status_code, 400)
        self.assertIn("Invalid email or password.", bad_login.text)


if __name__ == "__main__":
    unittest.main()
