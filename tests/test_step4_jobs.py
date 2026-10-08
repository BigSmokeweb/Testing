import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models import User, Site, Run, Usage, engine
from app.auth import create_session_token, SESSION_COOKIE_NAME, hash_password
from app.jobs import enqueue_run
from app.worker import run_job_entry


class TestJobsAndWorker(unittest.TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:6]
        with Session(engine) as session:
            user = User(email=f"worker_u_{suffix}@example.com", password_hash=hash_password("pw123456"), email_verified=True)
            session.add(user)
            session.commit()
            session.refresh(user)
            self.user_id = user.id

            site = Site(
                user_id=user.id,
                url="https://example.com",
                domain="example.com",
                verify_token="test_tok",
                verified_at=datetime.now(timezone.utc),
            )
            session.add(site)
            session.commit()
            session.refresh(site)
            self.site_id = site.id

        with Session(engine) as session:
            # Clear existing active runs from previous tests to avoid global concurrency limit in test suite
            active_runs = session.exec(select(Run).where(Run.status.in_(["queued", "running"]))).all()
            for r in active_runs:
                r.status = "completed"
                session.add(r)
            session.commit()

        self.user_token = create_session_token(self.user_id)


    def test_enqueue_run_and_worker_execution(self):
        c = TestClient(app, cookies={SESSION_COOKIE_NAME: self.user_token})

        # Get CSRF
        res = c.get("/sites")
        import re
        csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', res.text).group(1)

        # 1. Trigger Run test
        with patch("app.safety.resolve_hostname_ips", return_value=[__import__("ipaddress").ip_address("93.184.216.34")]):
            res_run = c.post(f"/sites/{self.site_id}/run", data={"csrf_token": csrf}, follow_redirects=False)
            self.assertEqual(res_run.status_code, 303)

        with Session(engine) as session:
            latest_run = session.exec(select(Run).where(Run.user_id == self.user_id).order_by(Run.id.desc())).first()
            self.assertIsNotNone(latest_run)
            self.assertEqual(latest_run.status, "queued")
            run_id = latest_run.id

        # 2. Check /runs/{id}/status endpoint returns JSON
        status_res = c.get(f"/runs/{run_id}/status")
        self.assertEqual(status_res.status_code, 200)
        self.assertEqual(status_res.json()["status"], "queued")

        # 3. Worker executes job
        with patch("app.worker.run_public_checks", return_value=None):
            run_job_entry(run_id)

        # 4. Status is now completed
        status_after = c.get(f"/runs/{run_id}/status")
        self.assertEqual(status_after.status_code, 200)
        self.assertEqual(status_after.json()["status"], "completed")

    def test_daily_limit_and_concurrency(self):
        with Session(engine) as session:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            usage = session.exec(select(Usage).where(Usage.user_id == self.user_id, Usage.date == today)).first()
            if not usage:
                usage = Usage(user_id=self.user_id, date=today, runs_count=5)
                session.add(usage)
            else:
                usage.runs_count = 5
                session.add(usage)
            session.commit()

        # Enqueue should be refused due to daily quota
        run, err = enqueue_run(self.user_id, self.site_id)
        self.assertIsNone(run)
        self.assertIn("Daily limit of 5 runs reached", err)


if __name__ == "__main__":
    unittest.main()
