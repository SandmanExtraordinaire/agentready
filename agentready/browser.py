"""Optional headless Chromium (Playwright). Every browser-based check must
degrade to SKIP when this returns None, so the scanner works without it.

Install:  pip install -e '.[browser]' && playwright install chromium
"""
from __future__ import annotations

from .agents import BROWSER_UA


class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self.error = ""

    def start(self) -> "Browser | None":
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            return self
        except Exception as e:  # not installed, no browser binary, sandbox issues...
            self.error = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
            self.close()
            return None

    def new_page(self):
        ctx = self._browser.new_context(user_agent=BROWSER_UA, viewport={"width": 1280, "height": 900},
                                        locale="en-US")
        ctx.set_default_timeout(15_000)
        return ctx.new_page()

    def render(self, url: str) -> tuple[str, str]:
        """Returns (rendered_html, visible_text)."""
        page = self.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            return page.content(), page.inner_text("body")
        finally:
            page.context.close()

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = self._pw = None
