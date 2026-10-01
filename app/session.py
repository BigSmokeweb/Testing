import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.config import load_config

AUTH_STATE_PATH = Path("auth/state.json")


def connect() -> None:
    """Opens a visible Chromium browser to let the user log in manually,

    then saves storage state upon terminal confirmation.
    """
    config = load_config()
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"Opening browser to {config.base_url} for manual login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(extra_http_headers=config.extra_headers)
        page = context.new_page()
        page.goto(config.base_url)

        input("Log in manually via SSO / MFA in browser window, then press [Enter] here to save session...")
        context.storage_state(path=str(AUTH_STATE_PATH))
        browser.close()

    print(f"Session saved to {AUTH_STATE_PATH}")


def is_valid() -> bool:
    """Checks if auth/state.json exists and if visiting base_url

    avoids redirecting to login url hints.
    """
    if not AUTH_STATE_PATH.is_file():
        return False

    config = load_config()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                storage_state=str(AUTH_STATE_PATH),
                extra_http_headers=config.extra_headers,
            )
            page = context.new_page()
            page.goto(config.base_url, wait_until="domcontentloaded")
            current_url = page.url.lower()

            for hint in config.login_url_hints:
                if hint.lower() in current_url:
                    return False
            return True
        except Exception:
            return False
        finally:
            browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.session [connect|check]")
        sys.exit(1)

    cmd = sys.argv[1].strip().lower()
    if cmd == "connect":
        connect()
    elif cmd == "check":
        if is_valid():
            print("VALID")
        else:
            print("EXPIRED")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m app.session [connect|check]")
        sys.exit(1)


if __name__ == "__main__":
    main()
