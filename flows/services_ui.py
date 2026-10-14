import re
from playwright.sync_api import expect

NAME = "About Page UI Verification"


def run(page, step, base_url):
    step("Open about page", lambda: page.goto(f"{base_url}/about", wait_until="domcontentloaded"))
    step("URL matches about path", lambda: expect(page).to_have_url(re.compile(r"/about")))
    step("Verify page has heading", lambda: expect(page.locator("h1, h2").first).to_be_visible())
    step("Verify main container has content", lambda: expect(page.locator("body")).to_be_visible())
