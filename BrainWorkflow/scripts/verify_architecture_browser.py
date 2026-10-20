"""Local-only browser acceptance for the project architecture graph."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys
from threading import Thread
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from wqb.desktop import find_browser
from wqb.project_architecture import load_architecture


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
ASSETS = PACKAGE / "management" / "architecture"


class FixtureHandler(BaseHTTPRequestHandler):
    """Serve only the graph frontend and real validated architecture for browser tests."""

    invalid = False

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/architecture":
            body = json.dumps({"error": "Invalid module dependency"} if self.invalid else load_architecture(ROOT / "milestone.md", ROOT)).encode()
            content_type = "application/json"
        else:
            filename = "index.html" if path == "/" else path.lstrip("/")
            asset = ASSETS / filename
            if not asset.is_file() or not asset.resolve().is_relative_to(ASSETS.resolve()):
                self.send_error(404)
                return
            body = asset.read_bytes()
            content_type = "text/html" if asset.suffix == ".html" else "text/javascript" if asset.suffix == ".js" else "text/css"
        self.send_response(422 if path == "/api/architecture" and self.invalid else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


def main() -> None:
    """Input: none. Output: screenshots and pass JSON; verify interactive graph in Edge."""
    output = PACKAGE / "output" / "architecture-browser"
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(find_browser()), headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.locator("#architecture-graph canvas").first.wait_for(timeout=10000)
            assert page.locator('[data-view="workflow"]').get_attribute("aria-pressed") == "true"
            assert "Objective and options" in page.locator("#module-detail h2").inner_text()
            page.screenshot(path=str(output / "workflow-desktop.png"), full_page=True)
            page.locator('.module-button[data-node="scout"]').click()
            assert "scout_seed" in page.locator("#module-detail").inner_text()
            page.locator('.module-button[data-node="seed"]').click()
            assert "scout_seed" in page.locator("#module-detail").inner_text()
            page.locator('.module-button[data-node="knowledge-compile"]').click()
            assert "separate" in page.locator("#module-detail").inner_text().lower()
            page.locator('.module-button[data-node="final-submit"]').click()
            assert "manual" in page.locator("#module-detail").inner_text().lower()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "workflow-mobile.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 900})
            page.locator('[data-view="modules"]').click()
            page.locator('.module-button[data-module="console"]').click()
            assert "Present runtime state" in page.locator("#module-detail").inner_text()
            page.get_by_role("searchbox", name="Search map").fill("repair")
            assert page.locator('.module-button[data-module="repair"]').is_visible()
            page.locator('.module-button[data-module="repair"]').click()
            assert "bounded improvements" in page.locator("#module-detail").inner_text()
            page.locator("#module-detail .dependency").filter(has_text="Assessment").first.click()
            assert "Assessment to Repair" in page.locator("#module-detail").inner_text()
            page.locator('.module-button[data-module="repair"]').click()
            page.screenshot(path=str(output / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            width = page.evaluate("document.documentElement.scrollWidth")
            assert width <= 390, f"mobile overflow: {width}px"
            FixtureHandler.invalid = True
            page.reload()
            assert "Invalid module dependency" in page.locator("#module-detail").inner_text()
            FixtureHandler.invalid = False
            page.goto(f"http://127.0.0.1:{server.server_port}/?module=repair")
            page.locator('[data-view="modules"][aria-pressed="true"]').wait_for()
            assert "Repair" in page.locator("#module-detail h2").inner_text()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps({"passed": True, "screenshots": str(output)}))


if __name__ == "__main__":
    main()
