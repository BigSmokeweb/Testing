from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
import time
from typing import Callable, List, Optional
from playwright.sync_api import sync_playwright

from app.config import load_config
from app.monitors import MonitorCollector, attach, record_load_time

AUTH_STATE_PATH = Path("auth/state.json")
ARTIFACTS_DIR = Path("artifacts")


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
        )

    # Failed on retry
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
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.runner <flow_path> [engine]")
        sys.exit(1)

    flow_path = sys.argv[1]
    engine = sys.argv[2] if len(sys.argv) > 2 else "chromium"

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
