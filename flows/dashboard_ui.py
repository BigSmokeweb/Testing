import re
from playwright.sync_api import expect

NAME = "Dashboard UI Verification"


def run(page, step, base_url):
    step("Navigate to dashboard", lambda: page.goto(f"{base_url}/dashboard", wait_until="domcontentloaded"))
    step("URL is dashboard", lambda: expect(page).to_have_url(re.compile(r"/dashboard")))
    step("Verify page body rendered", lambda: expect(page.locator("body")).to_be_visible())
    step("Verify dashboard content exists", lambda: expect(page.locator("main, [role='main'], body")).to_be_visible())
