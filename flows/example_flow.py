import re
from playwright.sync_api import expect

NAME = "Example Page Load"


def run(page, step, base_url):
    step("Open base URL", lambda: page.goto(base_url, wait_until="domcontentloaded"))
    step("URL is valid base", lambda: expect(page).to_have_url(re.compile(r"^https?://.*")))
    step("Body tag is present", lambda: expect(page.locator("body")).to_be_visible())
