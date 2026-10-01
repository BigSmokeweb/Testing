import os
from pathlib import Path
import threading
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import load_config
from app.models import (
    ConsoleLog,
    Flow,
    FlowResultModel,
    NetworkFailure,
    Run,
    StepResultModel,
    engine as db_engine,
    init_db,
)
from app.runner import run_suite
from app.session import is_valid as is_session_valid

app = FastAPI(title="AutoQA Dashboard")

# Mount static files and artifacts
STATIC_DIR = Path("app/static")
ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")

templates = Jinja2Templates(directory="app/templates")


def basename_filter(value):
    if not value:
        return ""
    return Path(value).name


templates.env.filters["basename"] = basename_filter


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    config = load_config()
    session_valid = is_session_valid()

    with Session(db_engine) as session:
        latest_run = session.exec(select(Run).order_by(Run.id.desc())).first()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "config": config,
            "session_valid": session_valid,
            "latest_run": latest_run,
        },
    )


@app.post("/run")
async def trigger_run(request: Request):
    body = await request.body()
    # Parse urlencoded body: engine=chromium
    engine = "chromium"
    try:
        from urllib.parse import parse_qs
        parsed = parse_qs(body.decode("utf-8"))
        if "engine" in parsed and parsed["engine"]:
            engine = parsed["engine"][0]
    except Exception:
        pass

    thread = threading.Thread(target=run_suite, args=(engine,), daemon=True)
    thread.start()
    return RedirectResponse(url="/history", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    with Session(db_engine) as session:
        runs = session.exec(select(Run).order_by(Run.id.desc())).all()
        run_data = []
        for r in runs:
            flow_results = session.exec(
                select(FlowResultModel).where(FlowResultModel.run_id == r.id)
            ).all()
            passed = sum(1 for fr in flow_results if fr.status == "passed")
            failed = sum(1 for fr in flow_results if fr.status == "failed")
            flaky = sum(1 for fr in flow_results if fr.status == "flaky")
            run_data.append(
                {
                    "id": r.id,
                    "started_at": r.started_at,
                    "engine": r.engine,
                    "status": r.status,
                    "passed_count": passed,
                    "failed_count": failed,
                    "flaky_count": flaky,
                }
            )

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "runs": run_data,
        },
    )


@app.get("/report/{run_id}", response_class=HTMLResponse)
def report(request: Request, run_id: int):
    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        if not run:
            return HTMLResponse(content="Run not found", status_code=404)

        flow_results = session.exec(
            select(FlowResultModel).where(FlowResultModel.run_id == run.id)
        ).all()

        flows_detail = []
        for fr in flow_results:
            flow_obj = session.get(Flow, fr.flow_id)
            steps = session.exec(
                select(StepResultModel)
                .where(StepResultModel.flow_result_id == fr.id)
                .order_by(StepResultModel.step_index.asc())
            ).all()
            console_logs = session.exec(
                select(ConsoleLog).where(ConsoleLog.flow_result_id == fr.id)
            ).all()
            network_fails = session.exec(
                select(NetworkFailure).where(NetworkFailure.flow_result_id == fr.id)
            ).all()

            flows_detail.append(
                {
                    "result": fr,
                    "flow": flow_obj,
                    "steps": steps,
                    "console_logs": console_logs,
                    "network_failures": network_fails,
                }
            )

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "run": run,
            "flows": flows_detail,
        },
    )
