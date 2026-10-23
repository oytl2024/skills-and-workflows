"""Verify the Signboard card destination against the real local viewer."""

from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from wqb.desktop import find_browser


PACKAGE = Path(__file__).resolve().parents[1]
CARD = PACKAGE / "management" / "board" / "000-To-do-stock" / "000-project-architecture-c5vpa.md"


def main() -> None:
    """Input: running viewer. Output: JSON result; click validated code/test/task links in Edge."""
    match = re.search(r"http://127\.0\.0\.1:8766/", CARD.read_text(encoding="utf-8"))
    assert match, "Signboard architecture card has no fixed local URL"
    url = match.group(0)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(find_browser()), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(url)
        page.locator("#architecture-graph canvas").first.wait_for(timeout=10000)
        assert page.locator('[data-view="workflow"]').get_attribute("aria-pressed") == "true"
        page.locator('.module-button[data-node="final-submit"]').click()
        assert "manual" in page.locator("#module-detail").inner_text().lower()
        page.locator('[data-view="modules"]').click()
        page.locator('.module-button[data-module="repair"]').click()
        links = page.locator("#module-detail .reference-list a")
        code_url = links.nth(0).get_attribute("href")
        test_url = links.nth(1).get_attribute("href")
        task_url = links.last.get_attribute("href")
        page.goto(url + code_url)
        assert "repair" in page.locator("body").inner_text().lower()
        page.goto(url + test_url)
        assert "Repair" in page.locator("body").inner_text()
        page.goto(url + task_url)
        assert "Current mainline" in page.locator("body").inner_text()
        browser.close()
    print(json.dumps({"passed": True, "card_url": url, "checked": [code_url, test_url, task_url]}))


if __name__ == "__main__":
    main()
