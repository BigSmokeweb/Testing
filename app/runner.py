from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import sys
import time
from typing import Callable, List, Optional
from playwright.sync_api import sync_playwright

from app.config import load_config

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
            trace_path=res1.trace_path,  # preserve failure trace from attempt 1
        )

    # If retry also fails, mark failed
    return FlowResult(
        name=res2.name,
        status="failed",
        attempts=2,
        duration_ms=res1.duration_ms + res2.duration_ms,
        steps=res2.steps,
        trace_path=res2.trace_path or res1.trace_path,
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.runner <flow_path> [engine]")
        sys.exit(1)

    flow_path = sys.argv[1]
    engine = sys.argv[2] if len(sys.argv) > 2 else "chromium"

    result = run_flow(flow_path, engine)
    print(f"\nFlow: {result.name} | Status: {result.status.upper()} | Attempts: {result.attempts} | Duration: {result.duration_ms}ms")
    for idx, s in enumerate(result.steps, start=1):
        line = f"  [{s.status.upper()}] Step {idx}: {s.description} ({s.duration_ms}ms)"
        if s.error_message:
            line += f" -> Error: {s.error_message}"
        if s.screenshot_path:
            line += f" -> Screenshot: {s.screenshot_path}"
        print(line)

    if result.trace_path:
        print(f"Trace saved: {result.trace_path}")


if __name__ == "__main__":
    main()
