import os
from datetime import datetime, timezone
from typing import List, Optional
from sqlmodel import Field, Session, SQLModel, create_engine, select

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///autoqa.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    email_verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Suite(SQLModel, table=True):
    __tablename__ = "suites"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None


class Flow(SQLModel, table=True):
    __tablename__ = "flows"
    id: Optional[int] = Field(default=None, primary_key=True)
    suite_id: Optional[int] = Field(default=None, foreign_key="suites.id")
    name: str
    file_path: str
    enabled: bool = True


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    suite_id: Optional[int] = Field(default=None, foreign_key="suites.id")
    engine: str = "chromium"
    status: str  # completed | session_expired | queued | running | failed | blocked | expired
    started_at: str
    finished_at: str
    duration_ms: int = 0
    session_valid: bool = True
    user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    site_id: Optional[int] = Field(default=None)
    mode: Optional[str] = Field(default=None)  # public | credentials
    queued_at: Optional[str] = Field(default=None)


class FlowResultModel(SQLModel, table=True):
    __tablename__ = "flow_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="runs.id")
    flow_id: Optional[int] = Field(default=None, foreign_key="flows.id")
    status: str  # passed | failed | flaky | skipped
    attempts: int
    duration_ms: int
    trace_path: Optional[str] = None


class StepResultModel(SQLModel, table=True):
    __tablename__ = "step_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_result_id: int = Field(foreign_key="flow_results.id")
    step_index: int
    description: str
    status: str  # passed | failed | skipped
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    duration_ms: int


class ConsoleLog(SQLModel, table=True):
    __tablename__ = "console_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_result_id: int = Field(foreign_key="flow_results.id")
    level: str
    message: str
    page_url: str
    timestamp: str


class NetworkFailure(SQLModel, table=True):
    __tablename__ = "network_failures"
    id: Optional[int] = Field(default=None, primary_key=True)
    flow_result_id: int = Field(foreign_key="flow_results.id")
    url: str
    method: str
    status_code: int
    page_url: str
    timestamp: str


class LinkCheck(SQLModel, table=True):
    __tablename__ = "link_checks"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="runs.id")
    source_url: str
    target_url: str
    status_code: int
    ok: bool


def init_db():
    SQLModel.metadata.create_all(engine)


def get_or_create_default_suite(session: Session) -> Suite:
    suite = session.exec(select(Suite).where(Suite.name == "Default Suite")).first()
    if not suite:
        suite = Suite(name="Default Suite", description="Default test suite")
        session.add(suite)
        session.commit()
        session.refresh(suite)
    return suite


def get_or_create_flow(session: Session, suite_id: int, name: str, file_path: str) -> Flow:
    flow = session.exec(select(Flow).where(Flow.file_path == file_path)).first()
    if not flow:
        flow = Flow(suite_id=suite_id, name=name, file_path=file_path, enabled=True)
        session.add(flow)
        session.commit()
        session.refresh(flow)
    return flow


def save_run(run_data: dict) -> Run:
    """Stores full suite run record into database."""
    init_db()
    with Session(engine) as session:
        suite = get_or_create_default_suite(session)

        run = Run(
            suite_id=suite.id,
            engine=run_data["engine"],
            status=run_data["status"],
            started_at=run_data["started_at"],
            finished_at=run_data["finished_at"],
            duration_ms=run_data["duration_ms"],
            session_valid=run_data["session_valid"],
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        for flow_res in run_data.get("flow_results", []):
            flow = get_or_create_flow(
                session,
                suite_id=suite.id,
                name=flow_res["name"],
                file_path=flow_res.get("file_path", ""),
            )
            flow_record = FlowResultModel(
                run_id=run.id,
                flow_id=flow.id,
                status=flow_res["status"],
                attempts=flow_res["attempts"],
                duration_ms=flow_res["duration_ms"],
                trace_path=flow_res.get("trace_path"),
            )
            session.add(flow_record)
            session.commit()
            session.refresh(flow_record)

            for idx, step in enumerate(flow_res.get("steps", []), start=1):
                step_record = StepResultModel(
                    flow_result_id=flow_record.id,
                    step_index=idx,
                    description=step.description,
                    status=step.status,
                    error_message=step.error_message,
                    screenshot_path=step.screenshot_path,
                    duration_ms=step.duration_ms,
                )
                session.add(step_record)

            for c_log in flow_res.get("console_errors", []):
                session.add(
                    ConsoleLog(
                        flow_result_id=flow_record.id,
                        level="error",
                        message=c_log["message"],
                        page_url=c_log["page_url"],
                        timestamp=c_log["timestamp"],
                    )
                )

            for net_fail in flow_res.get("network_failures", []):
                session.add(
                    NetworkFailure(
                        flow_result_id=flow_record.id,
                        url=net_fail["url"],
                        method=net_fail["method"],
                        status_code=net_fail["status_code"],
                        page_url=net_fail["page_url"],
                        timestamp=net_fail["timestamp"],
                    )
                )

        session.commit()
        session.refresh(run)
        session.expunge(run)
        return run


def save_link_checks(results: list) -> None:
    """Persist a list of link check result dicts into the link_checks table."""
    if not results:
        return
    with Session(engine) as session:
        for r in results:
            session.add(
                LinkCheck(
                    run_id=r["run_id"],
                    source_url=r["source_url"],
                    target_url=r["target_url"],
                    status_code=r["status_code"],
                    ok=r["ok"],
                )
            )
        session.commit()


def get_link_checks(run_id: int) -> list:
    """Return all link check results for a given run."""
    with Session(engine) as session:
        return session.exec(
            select(LinkCheck).where(LinkCheck.run_id == run_id)
        ).all()
