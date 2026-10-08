import ipaddress
import os
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlmodel import Session, select

from app.models import LinkCheck, Page, Run, Site, User, engine
from app.public_checks import run_public_checks


class TestStep5PublicChecks(unittest.TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:6]
        with Session(engine) as session:
            user = User(
                email=f"crawler_{suffix}@example.com",
                password_hash="argon2_fake_hash",
                email_verified=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            self.user_id = user.id

            site = Site(
                user_id=user.id,
                url="https://crawler-test.example.com",
                domain="crawler-test.example.com",
                verify_token="test_crawler_tok",
                verified_at=datetime.now(timezone.utc),
            )
            session.add(site)
            session.commit()
            session.refresh(site)
            self.site_id = site.id

            run = Run(
                user_id=user.id,
                site_id=site.id,
                mode="public",
                engine="chromium",
                status="queued",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at="",
                duration_ms=0,
                session_valid=True,
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            self.run_id = run.id

    @patch("app.public_checks.sync_playwright")
    @patch("app.public_checks.requests.get")
    @patch("app.safety.resolve_hostname_ips")
    def test_crawler_execution_records_pages_links_and_score(
        self, mock_resolve_ips, mock_requests_get, mock_sync_pw
    ):
        mock_resolve_ips.return_value = [ipaddress.ip_address("93.184.216.34")]

        # Mock requests.get for internal link checking
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests_get.return_value = mock_resp

        # Mock Playwright
        mock_pw = MagicMock()
        mock_sync_pw.return_value.__enter__.return_value = mock_pw
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        # Mock page response
        mock_nav_response = MagicMock()
        mock_nav_response.status = 200
        mock_page.goto.return_value = mock_nav_response

        # Mock internal link extraction from page 1
        mock_page.eval_on_selector_all.return_value = [
            "/about",
            "/contact",
            "https://crawler-test.example.com/broken",
            "https://external.com/out",
        ]

        # Execute crawler
        run_public_checks(self.run_id)

        # Verify DB records
        with Session(engine) as session:
            pages = session.exec(select(Page).where(Page.run_id == self.run_id)).all()
            self.assertGreaterEqual(len(pages), 1)
            first_page = pages[0]
            self.assertEqual(first_page.status_code, 200)

            # Check links were checked
            links = session.exec(select(LinkCheck).where(LinkCheck.run_id == self.run_id)).all()
            self.assertGreaterEqual(len(links), 1)

            # Check Run score
            run = session.get(Run, self.run_id)
            self.assertIsNotNone(run.score)
            self.assertEqual(run.score, 100)


if __name__ == "__main__":
    unittest.main()
