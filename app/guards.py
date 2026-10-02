from typing import List
from urllib.parse import urlparse
from playwright.sync_api import Locator, Page, Route


class RefusedActionError(Exception):
    """Raised when safe_click refuses an action matching never_click list."""
    pass


def setup_domain_guard(page: Page, allowed_domains: List[str]) -> None:
    """Blocks any network request whose hostname is outside allowed_domains

    and logs the blocked URL.
    """
    allowed_set = {d.lower() for d in allowed_domains}

    def route_handler(route: Route):
        req_url = route.request.url
        try:
            parsed = urlparse(req_url)
            hostname = (parsed.hostname or "").lower()

            # Allow data / blob or internal URLs
            if parsed.scheme in ("data", "blob", "about"):
                route.continue_()
                return

            if any(hostname == ad or hostname.endswith("." + ad) for ad in allowed_set):
                route.continue_()
            else:
                print(f"[Guard] Blocked request outside allowed domains: {req_url}")
                route.abort()
        except Exception:
            route.continue_()

    page.route("**/*", route_handler)


def safe_click(locator: Locator, never_click: List[str]) -> None:
    """Refuses to click any element whose visible text or aria-label

    matches any entry in never_click. Raises RefusedActionError if refused.
    """
    never_list = [item.lower().strip() for item in never_click]

    # Check element text and aria-label
    element_text = ""
    aria_label = ""
    try:
        element_text = (locator.inner_text(timeout=2000) or "").lower().strip()
    except Exception:
        pass

    try:
        aria_label = (locator.get_attribute("aria-label") or "").lower().strip()
    except Exception:
        pass

    target_content = f"{element_text} {aria_label}".strip()

    for forbidden in never_list:
        if forbidden in target_content or forbidden in element_text or forbidden in aria_label:
            raise RefusedActionError(
                f"safe_click refused: element matches protected keyword '{forbidden}' "
                f"(text='{element_text}', aria-label='{aria_label}')"
            )

    locator.click()
