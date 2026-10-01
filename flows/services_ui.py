import re
from playwright.sync_api import expect

NAME = "Legal Services UI Verification"


def run(page, step, base_url):
    step("Open legal notice service page", lambda: page.goto(f"{base_url}/legal-notice.html", wait_until="domcontentloaded"))
    step("URL matches legal notice", lambda: expect(page).to_have_url(re.compile(r"/legal-notice\.html")))
    step("Verify page has heading", lambda: expect(page.locator("h1, h2").first).to_be_visible())
    step("Verify main container has readable content", lambda: expect(page.locator("body")).to_contain_text("Legal"))
