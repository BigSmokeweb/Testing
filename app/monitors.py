from dataclasses import dataclass, field
import datetime
from typing import List, Optional
from playwright.sync_api import Page, Response


@dataclass
class ConsoleErrorLog:
    message: str
    page_url: str
    timestamp: str


@dataclass
class NetworkFailureLog:
    url: str
    method: str
    status_code: int
    page_url: str
    timestamp: str


@dataclass
class MonitorCollector:
    console_errors: List[ConsoleErrorLog] = field(default_factory=list)
    network_failures: List[NetworkFailureLog] = field(default_factory=list)
    page_load_time_ms: Optional[int] = None


def attach(page: Page, collector: MonitorCollector) -> None:
    """Attaches console error listener and network response failure listener.

    Also exposes a method to read page load duration from navigation timing.
    """
    def on_console(msg):
        if msg.type == "error":
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            collector.console_errors.append(
                ConsoleErrorLog(
                    message=msg.text,
                    page_url=page.url,
                    timestamp=now,
                )
            )

    def on_response(response: Response):
        if response.status >= 400:
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            collector.network_failures.append(
                NetworkFailureLog(
                    url=response.url,
                    method=response.request.method,
                    status_code=response.status,
                    page_url=page.url,
                    timestamp=now,
                )
            )

    page.on("console", on_console)
    page.on("response", on_response)


def record_load_time(page: Page, collector: MonitorCollector) -> None:
    """Reads navigation timing from browser if available."""
    try:
        timing = page.evaluate(
            "() => window.performance.timing ? "
            "(window.performance.timing.loadEventEnd - window.performance.timing.navigationStart) : 0"
        )
        if isinstance(timing, (int, float)) and timing > 0:
            collector.page_load_time_ms = int(timing)
    except Exception:
        pass
