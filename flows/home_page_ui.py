import re
from playwright.sync_api import expect

NAME = "Home Page Load and Navigation"


def run(page, step, base_url):
    step("Open homepage", lambda: page.goto(base_url, wait_until="domcontentloaded"))
    step("Page title is non-empty", lambda: expect(page).to_have_title(re.compile(r".+")))
    step("Verify page body rendered", lambda: expect(page.locator("body")).to_be_visible())
    step("Verify navigation or links present", lambda: expect(page.locator("a, nav, header").first).to_be_attached())
