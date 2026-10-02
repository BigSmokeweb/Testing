from dataclasses import dataclass, field
import datetime
import importlib.util
from pathlib import Path
import sys
import time
from typing import Callable, List, Optional
from playwright.sync_api import sync_playwright

from app.config import load_config
from app.guards import setup_domain_guard, RefusedActionError
from app.monitors import MonitorCollector, attach, record_load_time
from app.session import is_valid as is_session_valid
from app.models import save_run, init_db
from app.alerts import send_alert

AUTH_STATE_PATH = Path("auth/state.json")
ARTIFACTS_DIR = Path("artifacts")
FLOWS_DIR = Path("flows")


@dataclass
class StepResult:
    description: str
    status: str  # passed | failed | skipped
    duration_ms: int = 0
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None


@dataclass
class FlowResult:
    name: str
    status: str  # passed | failed | flaky
    attempts: int
    duration_ms: int
    steps: List[StepResult] = field(default_factory=list)
    trace_path: Optional[str] = None
    console_errors: List[dict] = field(default_factory=list)
    network_failures: List[dict] = field(default_factory=list)
    page_load_time_ms: Optional[int] = None
    file_path: Optional[str] = None


def load_flow_module(flow_path: str):
    path = Path(flow_path)
    if not path.is_file():
        raise FileNotFoundError(f"Flow file '{flow_path}' not found.")
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for flow '{flow_path}'.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "NAME") or not hasattr(module, "run"):
        raise AttributeError(f"Flow '{flow_path}' must define NAME and run(page, step, base_url).")
    return module


def _execute_attempt(module, engine: str, attempt_num: int) -> FlowResult:
    config = load_config()
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    trace_file = ARTIFACTS_DIR / f"{Path(module.__file__).stem}_attempt{attempt_num}_{timestamp}.zip"

    steps: List[StepResult] = []
    has_failed = False
    start_time = time.time()
    collector = MonitorCollector()

    with sync_playwright() as p:
        browser_type = getattr(p, engine.lower(), None)
        if browser_type is None:
            raise ValueError(f"Unsupported engine: {engine}. Use chromium, firefox, or webkit.")

        browser = browser_type.launch(headless=True)
        context_kwargs = {"extra_http_headers": config.extra_headers}
        if AUTH_STATE_PATH.is_file():
            context_kwargs["storage_state"] = str(AUTH_STATE_PATH)

        context = browser.new_context(**context_kwargs)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()

        # Attach monitors
        attach(page, collector)

        # Attach domain guard: abort requests outside allowed_domains
        setup_domain_guard(page, config.allowed_domains)

        def step(description: str, fn: Callable[[], None]) -> None:
            nonlocal has_failed
            if has_failed:
                steps.append(StepResult(description=description, status="skipped"))
                return

            step_start = time.time()
            try:
                fn()
                duration = int((time.time() - step_start) * 1000)
                steps.append(StepResult(description=description, status="passed", duration_ms=duration))
            except RefusedActionError as e:
                # safe_click refused: record as skipped, do NOT fail the flow
                duration = int((time.time() - step_start) * 1000)
                steps.append(
                    StepResult(
                        description=description,
                        status="skipped",
                        duration_ms=duration,
                        error_message=f"[Guard] {e}",
                    )
                )
            except Exception as e:
                has_failed = True
                duration = int((time.time() - step_start) * 1000)
                shot_path = ARTIFACTS_DIR / f"fail_{Path(module.__file__).stem}_{timestamp}.png"
                try:
                    page.screenshot(path=str(shot_path))
                    saved_shot = str(shot_path)
                except Exception:
                    saved_shot = None
                steps.append(
                    StepResult(
                        description=description,
                        status="failed",
                        duration_ms=duration,
                        error_message=str(e),
                        screenshot_path=saved_shot,
                    )
                )

        try:
            module.run(page, step, config.base_url)
            record_load_time(page, collector)
        except Exception as e:
            if not has_failed:
                has_failed = True
                steps.append(
                    StepResult(
                        description="Flow execution error",
                        status="failed",
                        error_message=str(e),
                    )
                )

        total_duration = int((time.time() - start_time) * 1000)
        trace_saved = None
        if has_failed:
            context.tracing.stop(path=str(trace_file))
            trace_saved = str(trace_file)
        else:
            context.tracing.stop()

        browser.close()

    status = "failed" if has_failed else "passed"
    return FlowResult(
        name=getattr(module, "NAME", "Unnamed Flow"),
        status=status,
        attempts=attempt_num,
        duration_ms=total_duration,
        steps=steps,
        trace_path=trace_saved,
        console_errors=[
            {"message": err.message, "page_url": err.page_url, "timestamp": err.timestamp}
            for err in collector.console_errors
        ],
        network_failures=[
            {
                "url": fail.url,
                "method": fail.method,
                "status_code": fail.status_code,
                "page_url": fail.page_url,
                "timestamp": fail.timestamp,
            }
            for fail in collector.network_failures
        ],
        page_load_time_ms=collector.page_load_time_ms,
        file_path=str(Path(module.__file__).as_posix()),
    )


def run_flow(flow_path: str, engine: str = "chromium") -> FlowResult:
    module = load_flow_module(flow_path)

    # First attempt
    res1 = _execute_attempt(module, engine, attempt_num=1)
    if res1.status == "passed":
        return res1

    # Retry once in fresh context
    res2 = _execute_attempt(module, engine, attempt_num=2)
    if res2.status == "passed":
        return FlowResult(
            name=res2.name,
            status="flaky",
            attempts=2,
            duration_ms=res1.duration_ms + res2.duration_ms,
            steps=res2.steps,
            trace_path=res1.trace_path,
            console_errors=res1.console_errors + res2.console_errors,
            network_failures=res1.network_failures + res2.network_failures,
            page_load_time_ms=res2.page_load_time_ms or res1.page_load_time_ms,
            file_path=str(Path(flow_path).as_posix()),
        )

    return FlowResult(
        name=res2.name,
        status="failed",
        attempts=2,
        duration_ms=res1.duration_ms + res2.duration_ms,
        steps=res2.steps,
        trace_path=res2.trace_path or res1.trace_path,
        console_errors=res1.console_errors + res2.console_errors,
        network_failures=res1.network_failures + res2.network_failures,
        page_load_time_ms=res2.page_load_time_ms or res1.page_load_time_ms,
        file_path=str(Path(flow_path).as_posix()),
    )


def run_suite(engine: str = "chromium"):
    start_dt = datetime.datetime.now(datetime.timezone.utc)
    started_at = start_dt.isoformat()
    start_time = time.time()

    # 1. Check session validity first
    valid = is_session_valid()
    if not valid:
        end_dt = datetime.datetime.now(datetime.timezone.utc)
        duration_ms = int((time.time() - start_time) * 1000)
        run_record = save_run(
            {
                "engine": engine,
                "status": "session_expired",
                "started_at": started_at,
                "finished_at": end_dt.isoformat(),
                "duration_ms": duration_ms,
                "session_valid": False,
                "flow_results": [],
            }
        )
        print("Session expired or invalid! Stopped suite execution.")
        return run_record

    # 2. Run all flow files not starting with underscore
    flow_files = sorted(
        [
            p
            for p in FLOWS_DIR.glob("*.py")
            if not p.name.startswith("_") and p.is_file()
        ]
    )

    flow_results_data = []
    for flow_p in flow_files:
        print(f"Running flow: {flow_p.name}...")
        res = run_flow(str(flow_p), engine)
        flow_results_data.append(
            {
                "name": res.name,
                "file_path": str(flow_p.as_posix()),
                "status": res.status,
                "attempts": res.attempts,
                "duration_ms": res.duration_ms,
                "trace_path": res.trace_path,
                "steps": res.steps,
                "console_errors": res.console_errors,
                "network_failures": res.network_failures,
            }
        )

    end_dt = datetime.datetime.now(datetime.timezone.utc)
    duration_ms = int((time.time() - start_time) * 1000)

    run_record = save_run(
        {
            "engine": engine,
            "status": "completed",
            "started_at": started_at,
            "finished_at": end_dt.isoformat(),
            "duration_ms": duration_ms,
            "session_valid": True,
            "flow_results": flow_results_data,
        }
    )
    print(f"Suite completed. Run ID: {run_record.id} saved to DB.")

    # Send Slack alert if any flows failed
    failed_names = [r["name"] for r in flow_results_data if r["status"] == "failed"]
    send_alert(run_id=run_record.id, engine=engine, failed_flows=failed_names)

    return run_record


def main():
    # Ensure UTF-8 output on Windows terminals (avoids cp1252 UnicodeEncodeError)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m app.runner <flow_path> [engine]")
        print("  python -m app.runner suite [engine]")
        sys.exit(1)

    first_arg = sys.argv[1]
    engine = sys.argv[2] if len(sys.argv) > 2 else "chromium"

    if first_arg == "suite":
        run_suite(engine)
    else:
        flow_path = first_arg
        result = run_flow(flow_path, engine)
        print(f"\nFlow: {result.name} | Status: {result.status.upper()} | Attempts: {result.attempts} | Duration: {result.duration_ms}ms")
        if result.page_load_time_ms is not None:
            print(f"Page Load Time: {result.page_load_time_ms}ms")
        for idx, s in enumerate(result.steps, start=1):
            line = f"  [{s.status.upper()}] Step {idx}: {s.description} ({s.duration_ms}ms)"
            if s.error_message:
                line += f" -> Error: {s.error_message}"
            if s.screenshot_path:
                line += f" -> Screenshot: {s.screenshot_path}"
            print(line)

        print(f"Console Errors: {len(result.console_errors)}")
        for err in result.console_errors:
            print(f"  - [Console Error] {err['message']} (url: {err['page_url']})")

        print(f"Network Failures (>=400): {len(result.network_failures)}")
        for fail in result.network_failures:
            print(f"  - [HTTP {fail['status_code']}] {fail['method']} {fail['url']}")

        if result.trace_path:
            print(f"Trace saved: {result.trace_path}")


if __name__ == "__main__":
    main()
