import re
from playwright.sync_api import expect

NAME = "Homepage & Services Navigation"


def run(page, step, base_url):
    step("Open homepage", lambda: page.goto(base_url, wait_until="domcontentloaded"))
    step("Page title contains brand", lambda: expect(page).to_have_title(re.compile(r"NoLegalPaisa", re.I)))
    step("Verify header logo or main brand text is visible", lambda: expect(page.locator("body")).to_contain_text("NoLegalPaisa"))
    step("Verify services section or navigation links present", lambda: expect(page.locator("a[href*='legal-notice']").first).to_be_attached())
