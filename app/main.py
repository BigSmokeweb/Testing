import os
from pathlib import Path
import threading
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session, select

from app.config import load_config
from app.models import (
    ConsoleLog,
    Flow,
    FlowResultModel,
    NetworkFailure,
    Run,
    Site,
    StepResultModel,
    User,
    engine as db_engine,
    init_db,
    get_link_checks,
    save_link_checks,
)
from app.sites import (
    add_site_for_user,
    get_user_sites,
    verify_site_ownership,
)
from app.jobs import enqueue_run
from app.runner import run_suite
from app.linkcheck import check_links
from app.session import is_valid as is_session_valid
from app.auth import (
    SESSION_COOKIE_NAME,
    get_current_user_from_token,
    create_session_token,
    generate_csrf_token,
    verify_csrf_token,
    hash_password,
    verify_password,
    normalize_and_validate_email,
)

limiter = Limiter(key_func=get_remote_address)
_is_local = os.getenv("LOCAL_MODE", "0") == "1"
app = FastAPI(
    title="AutoQA Dashboard",
    docs_url="/docs" if _is_local else None,
    redoc_url="/redoc" if _is_local else None,
    openapi_url="/openapi.json" if _is_local else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request=request, name="404.html",
        context={"user": user}, status_code=404)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request=request, name="500.html",
        context={"user": user}, status_code=500)

# Security event logger
import logging
security_logger = logging.getLogger("autoqa_security")
security_logger.setLevel(logging.INFO)
if not security_logger.handlers:
    sec_handler = logging.FileHandler("security.log", encoding="utf-8")
    sec_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    security_logger.addHandler(sec_handler)


def log_security_event(event_type: str, client_ip: str, details: str):
    """Logs security events (blocked URL, failed login, limit hit) to security.log without credentials."""
    security_logger.info(f"EVENT={event_type} IP={client_ip} DETAILS={details}")


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


import json as _json
def tojson_filter(value):
    return _json.dumps(value)


templates.env.filters["basename"] = basename_filter
templates.env.filters["tojson"] = tojson_filter


@app.on_event("startup")
def on_startup():
    init_db()


def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return get_current_user_from_token(token)


def get_or_create_csrf(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    return generate_csrf_token(token)


def is_authenticated(request: Request) -> bool:
    if os.getenv("LOCAL_MODE", "0") == "1":
        return True
    return get_current_user(request) is not None


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=303)
    csrf_token = get_or_create_csrf(request)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"csrf_token": csrf_token, "error": None, "user": None},
    )


@app.post("/register")
@limiter.limit("10/minute")
async def register_submit(request: Request):
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    email_raw = parsed.get("email", [""])[0].strip()
    password = parsed.get("password", [""])[0]
    csrf = parsed.get("csrf_token", [""])[0]

    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "csrf_token": get_or_create_csrf(request),
                "error": "Invalid CSRF token. Please reload.",
                "user": None,
            },
            status_code=400,
        )

    try:
        email = normalize_and_validate_email(email_raw)
    except Exception:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "csrf_token": get_or_create_csrf(request),
                "error": "Invalid email address.",
                "email": email_raw,
                "user": None,
            },
            status_code=400,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "csrf_token": get_or_create_csrf(request),
                "error": "Password must be at least 8 characters.",
                "email": email,
                "user": None,
            },
            status_code=400,
        )

    with Session(db_engine) as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={
                    "csrf_token": get_or_create_csrf(request),
                    "error": "Email already registered.",
                    "email": email,
                    "user": None,
                },
                status_code=400,
            )

        new_user = User(
            email=email,
            password_hash=hash_password(password),
            email_verified=False,
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        user_id = new_user.id

    token = create_session_token(user_id)
    next_url = request.query_params.get("next") or "/"
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=303)
    csrf_token = get_or_create_csrf(request)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"csrf_token": csrf_token, "error": None, "user": None},
    )


@app.post("/login")
@limiter.limit("10/minute")
async def login_submit(request: Request):
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    email_raw = parsed.get("email", [""])[0].strip()
    password = parsed.get("password", [""])[0]
    csrf = parsed.get("csrf_token", [""])[0]

    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": get_or_create_csrf(request),
                "error": "Invalid CSRF token. Please reload.",
                "user": None,
            },
            status_code=400,
        )

    generic_error = "Invalid email or password."
    try:
        email = normalize_and_validate_email(email_raw)
    except Exception:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": get_or_create_csrf(request),
                "error": generic_error,
                "email": email_raw,
                "user": None,
            },
            status_code=400,
        )

    with Session(db_engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user or not verify_password(password, user.password_hash):
            log_security_event("FAILED_LOGIN", get_remote_address(request), f"email_hash={hash(email)}")
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "csrf_token": get_or_create_csrf(request),
                    "error": generic_error,
                    "email": email_raw,
                    "user": None,
                },
                status_code=400,
            )
        user_id = user.id


    token = create_session_token(user_id)
    next_url = request.query_params.get("next") or "/"
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    config = load_config()
    session_valid = is_session_valid()
    csrf_token = get_or_create_csrf(request)

    with Session(db_engine) as session:
        latest_run = session.exec(select(Run).order_by(Run.id.desc())).first()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "config": config,
            "session_valid": session_valid,
            "latest_run": latest_run,
            "user": user,
            "csrf_token": csrf_token,
        },
    )


def _run_suite_and_linkcheck(engine: str) -> None:
    """Run full test suite then perform link check on all configured pages."""
    run_record = run_suite(engine)
    if run_record and run_record.id:
        results = check_links(run_record.id)
        save_link_checks(results)


@app.post("/run")
async def trigger_run(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]
    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"

    if os.getenv("LOCAL_MODE", "0") != "1" and not verify_csrf_token(csrf, session_tok):
        return HTMLResponse("Invalid CSRF token", status_code=400)

    engine = "chromium"
    if "engine" in parsed and parsed["engine"]:
        engine = parsed["engine"][0]

    thread = threading.Thread(target=_run_suite_and_linkcheck, args=(engine,), daemon=True)
    thread.start()
    return RedirectResponse(url="/history", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)
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
            site_obj = session.get(Site, r.site_id) if r.site_id else None
            run_data.append(
                {
                    "id": r.id,
                    "started_at": r.started_at,
                    "engine": r.engine,
                    "mode": r.mode if hasattr(r, "mode") else r.engine,
                    "status": r.status,
                    "score": r.score if hasattr(r, "score") else None,
                    "duration_ms": r.duration_ms,
                    "passed_count": passed,
                    "failed_count": failed,
                    "flaky_count": flaky,
                    "site": site_obj,
                }
            )

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "runs": run_data,
            "user": user,
        },
    )


@app.get("/report/{run_id}", response_class=HTMLResponse)
def report(request: Request, run_id: int):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    user = get_current_user(request)
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

        # Previous run for the same engine
        previous_run = session.exec(
            select(Run)
            .where(Run.engine == run.engine, Run.id < run.id)
            .order_by(Run.id.desc())
        ).first()

        prev_failed_flow_ids = set()
        if previous_run:
            prev_failed_results = session.exec(
                select(FlowResultModel).where(
                    FlowResultModel.run_id == previous_run.id,
                    FlowResultModel.status == "failed",
                )
            ).all()
            prev_failed_flow_ids = {fr.flow_id for fr in prev_failed_results}

        new_failures = []
        for fd in flows_detail:
            if fd["result"].status == "failed":
                if previous_run is None or fd["flow"].id not in prev_failed_flow_ids:
                    new_failures.append(fd)

    link_checks = get_link_checks(run_id)
    broken_links = [lc for lc in link_checks if not lc.ok]

    # Public-checks pages (v2 mode)
    from app.models import Page as PageModel
    pages_all = []
    try:
        pages_all = session.exec(select(PageModel).where(PageModel.run_id == run_id)).all()
    except Exception:
        pages_all = []

    error_pages = [p for p in pages_all if (p.status_code and p.status_code >= 400) or p.error]
    ok_pages = [p for p in pages_all if p not in error_pages]

    # avg load time
    load_times = [p.load_ms for p in pages_all if p.load_ms]
    avg_load_ms = (sum(load_times) / len(load_times)) if load_times else None

    # Attach site
    run_site = None
    if run.site_id:
        run_site = session.get(Site, run.site_id)

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={
            "run": run,
            "site": run_site,
            "flows": flows_detail,
            "pages": pages_all,
            "error_pages": error_pages,
            "ok_pages": ok_pages,
            "avg_load_ms": avg_load_ms,
            "previous_run": previous_run,
            "new_failures": new_failures,
            "link_checks": link_checks,
            "broken_links": broken_links,
            "user": user,
        },
    )


@app.get("/sites", response_class=HTMLResponse)
def sites_list(request: Request, error: str = None, success: str = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    sites = get_user_sites(user.id)
    csrf_token = get_or_create_csrf(request)

    return templates.TemplateResponse(
        request=request,
        name="sites.html",
        context={
            "user": user,
            "sites": sites,
            "csrf_token": csrf_token,
            "error": error,
            "success": success,
        },
    )


@app.post("/sites")
async def add_site(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]
    raw_url = parsed.get("url", [""])[0].strip()

    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/sites?error=Invalid+CSRF+token", status_code=303)

    site, err = add_site_for_user(user.id, raw_url)
    if err:
        log_security_event("BLOCKED_URL_OR_INVALID_SITE", get_remote_address(request), f"url={raw_url} reason={err}")
        from urllib.parse import quote_plus
        return RedirectResponse(url=f"/sites?error={quote_plus(err)}", status_code=303)

    return RedirectResponse(url="/sites?success=Site+added+successfully", status_code=303)



@app.post("/sites/{site_id}/verify")
async def verify_site(request: Request, site_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]

    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/sites?error=Invalid+CSRF+token", status_code=303)

    from datetime import datetime, timezone
    with Session(db_engine) as session:
        site = session.get(Site, site_id)
        if not site or site.user_id != user.id:
            return RedirectResponse(url="/sites?error=Site+not+found", status_code=303)

        if site.verified_at:
            return RedirectResponse(url="/sites?success=Site+is+already+verified", status_code=303)

        verified = verify_site_ownership(site)
        if not verified:
            return RedirectResponse(
                url="/sites?error=Verification+failed.+Ensure+DNS+record+or+verification+file+is+live.",
                status_code=303,
            )

        site.verified_at = datetime.now(timezone.utc)
        session.add(site)
        session.commit()

    return RedirectResponse(url="/sites?success=Site+verified+successfully!", status_code=303)


@app.post("/sites/{site_id}/run")
@limiter.limit("10/minute")
async def trigger_site_run(request: Request, site_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]

    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/sites?error=Invalid+CSRF+token", status_code=303)

    mode = parsed.get("mode", ["public"])[0]
    if mode == "credentials":
        login_url = parsed.get("login_url", [""])[0].strip()
        username = parsed.get("username", [""])[0].strip()
        password = parsed.get("password", [""])[0]
        if not login_url or not username or not password:
            return RedirectResponse(url="/sites?error=Missing+login+credentials", status_code=303)
        from app.creds import store_credentials
        store_credentials(site_id=site_id, login_url=login_url, username=username, password=password)

    run, err = enqueue_run(user.id, site_id, mode=mode)
    if err:
        log_security_event("RUN_LIMIT_OR_SAFETY_BLOCKED", get_remote_address(request), f"site_id={site_id} err={err}")
        from urllib.parse import quote_plus
        return RedirectResponse(url=f"/sites?error={quote_plus(err)}", status_code=303)

    return RedirectResponse(url=f"/runs/{run.id}/progress", status_code=303)


@app.post("/account/delete")
async def account_delete_route(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]
    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/sites?error=Invalid+CSRF+token", status_code=303)

    from app.auth import delete_user_account
    user_id = user.id
    log_security_event("ACCOUNT_DELETED", get_remote_address(request), f"user_id={user_id}")
    delete_user_account(user_id)

    response = RedirectResponse(url="/login?success=Account+deleted+successfully", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response




# --- Wizard & Public Landing Routes ---

@app.post("/wizard/start")
async def wizard_start(request: Request):
    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    url = parsed.get("url", [""])[0].strip()
    from urllib.parse import quote_plus
    user = get_current_user(request)
    if not user:
        # Redirect to register with target url preserved
        return RedirectResponse(url=f"/register?next=/wizard%3Furl%3D{quote_plus(url)}", status_code=303)
    return RedirectResponse(url=f"/wizard?url={quote_plus(url)}", status_code=303)


@app.get("/wizard", response_class=HTMLResponse)
def wizard_page(request: Request, url: str = "", site_id: int = None, error: str = None, success: str = None):
    user = get_current_user(request)
    if not user:
        from urllib.parse import quote_plus
        return RedirectResponse(url=f"/login?next=/wizard%3Furl%3D{quote_plus(url)}", status_code=303)

    csrf_token = get_or_create_csrf(request)
    site = None
    step = 1

    if site_id:
        with Session(db_engine) as session:
            s = session.get(Site, site_id)
            if s and s.user_id == user.id:
                site = s
                step = 3 if s.verified_at else 2

    return templates.TemplateResponse(
        request=request,
        name="wizard.html",
        context={
            "step": step,
            "site": site,
            "target_url": url,
            "csrf_token": csrf_token,
            "error": error,
            "success": success,
            "user": user,
        },
    )


@app.post("/wizard/step1")
async def wizard_step1(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]
    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/wizard?error=Invalid+CSRF+token", status_code=303)

    raw_url = parsed.get("url", [""])[0].strip()
    authorized = parsed.get("authorized", [""])[0]
    if not authorized:
        from urllib.parse import quote_plus
        return RedirectResponse(url=f"/wizard?url={quote_plus(raw_url)}&error=You+must+confirm+you+are+authorized+to+test+this+site", status_code=303)

    site, err = add_site_for_user(user.id, raw_url)
    if err:
        from urllib.parse import quote_plus
        return RedirectResponse(url=f"/wizard?url={quote_plus(raw_url)}&error={quote_plus(err)}", status_code=303)

    if site.verified_at:
        return RedirectResponse(url=f"/wizard?site_id={site.id}", status_code=303)
    return RedirectResponse(url=f"/wizard?site_id={site.id}", status_code=303)


@app.post("/wizard/step2/verify")
async def wizard_step2_verify(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    body = await request.body()
    parsed = parse_qs(body.decode("utf-8"))
    csrf = parsed.get("csrf_token", [""])[0]
    session_tok = request.cookies.get(SESSION_COOKIE_NAME) or "anon"
    if not verify_csrf_token(csrf, session_tok):
        return RedirectResponse(url="/wizard?error=Invalid+CSRF+token", status_code=303)

    site_id_str = parsed.get("site_id", [""])[0]
    try:
        site_id = int(site_id_str)
    except ValueError:
        return RedirectResponse(url="/wizard?error=Invalid+site", status_code=303)

    from datetime import datetime, timezone
    with Session(db_engine) as session:
        site = session.get(Site, site_id)
        if not site or site.user_id != user.id:
            return RedirectResponse(url="/wizard?error=Site+not+found", status_code=303)

        if not site.verified_at:
            if not verify_site_ownership(site):
                return RedirectResponse(
                    url=f"/wizard?site_id={site_id}&error=Verification+failed.+Ensure+DNS+record+or+hosted+file+is+live.",
                    status_code=303
                )
            site.verified_at = datetime.now(timezone.utc)
            session.add(site)
            session.commit()

    return RedirectResponse(url=f"/wizard?site_id={site_id}&success=Domain+ownership+verified!", status_code=303)


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={
            "user": user,
            "title": "Terms of Service - AutoQA",
            "content": """
            <div class="card" style="max-width: 800px; margin: 30px auto;">
              <h2>Terms of Service</h2>
              <p>By using AutoQA, you agree that you will only test domains that you own or have explicit authorization to test.</p>
              <p>AutoQA enforces strict SSRF protections and rate limits. Any attempt to bypass security boundaries or use the service for denial of service is prohibited.</p>
            </div>
            """
        }
    )


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context={
            "user": user,
            "title": "Privacy Policy - AutoQA",
            "content": """
            <div class="card" style="max-width: 800px; margin: 30px auto;">
              <h2>Privacy Policy</h2>
              <p>We do not sell personal data. Passwords are encrypted with Argon2. Test credentials are encrypted with Fernet and automatically purged upon test completion.</p>
              <p>You can permanently delete your account and all associated test data at any time via the Danger Zone on your My Sites page.</p>
            </div>
            """
        }
    )


@app.get("/runs/{run_id}/progress", response_class=HTMLResponse)
def run_progress_page(request: Request, run_id: int):
    user = get_current_user(request)
    if not user and os.getenv("LOCAL_MODE", "0") != "1":
        return RedirectResponse(url="/login", status_code=303)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        if not run:
            return RedirectResponse(url="/history", status_code=303)
        if user and run.user_id and run.user_id != user.id:
            return RedirectResponse(url="/history", status_code=303)

        # If already done, redirect to report
        if run.status in ("completed", "failed", "expired"):
            return RedirectResponse(url=f"/report/{run_id}", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="progress.html",
        context={"run": run, "user": user},
    )


@app.get("/runs/{run_id}/status")
def get_run_status(request: Request, run_id: int):
    user = get_current_user(request)
    if not user and os.getenv("LOCAL_MODE", "0") != "1":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    with Session(db_engine) as session:
        run = session.get(Run, run_id)
        if not run:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if user and run.user_id and run.user_id != user.id:
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        # Count pages checked so far
        from app.models import Page as PageModel
        pages_count = 0
        try:
            from sqlmodel import func
            pages_count = session.exec(
                select(func.count()).where(PageModel.run_id == run.id)
            ).one()
        except Exception:
            pass

        return JSONResponse({
            "id": run.id,
            "status": run.status,
            "duration_ms": run.duration_ms,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "pages_checked": pages_count,
        })



