"""Run a full scan of one store."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from .browser import Browser
from .checks import ScanContext, run_all
from .discover import discover
from .http import Fetcher
from .models import ScanResult
from .scoring import score
from .ucp_schema import latest_version


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def scan(target: str, *, max_products: int = 4, product_urls: list[str] | None = None,
         category_urls: list[str] | None = None, use_browser: bool = True,
         delay: float = 0.6, verify_tls: bool = True, log=print) -> ScanResult:
    fx = Fetcher(delay=delay, verify=verify_tls)
    browser = None
    browser_error = ""
    try:
        log(f"• Discovering pages on {target}")
        d = discover(fx, target, max_products=max_products,
                     product_urls=product_urls, category_urls=category_urls)
        result = ScanResult(domain=urlparse(d.base_url).netloc, base_url=d.base_url,
                            started_at=_now(), ucp_schema_version=latest_version())
        result.pages = d.pages
        result.notes += d.notes
        for p in d.pages:
            log(f"  {p.kind:<9} {p.status or '—'}  {p.url}")

        if use_browser:
            b = Browser()
            browser = b.start()
            browser_error = b.error
            if browser is None:
                log(f"• Browser unavailable, browser checks will be skipped ({browser_error})")
                result.notes.append("Browser-based checks were skipped (headless Chromium not available).")
        ctx = ScanContext(fetcher=fx, discovery=d, browser=browser, browser_error=browser_error)

        log("• Running checks")
        result.findings = run_all(ctx)
        score(result)
        result.finished_at = _now()
        log(f"• {result.domain}: {result.tier} · score {result.score:.0f}/100 · {fx.request_count} requests")
        return result
    finally:
        if browser:
            browser.close()
        fx.close()
