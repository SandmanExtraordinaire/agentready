"""Optional headless-browser pass (Playwright).

Runs once per scan and caches results in ctx.shared["browser"]:
  - rendered text of product pages (to measure JavaScript dependency)
  - a shopping task probe: product page -> add to cart -> cart -> checkout.
The probe never enters contact or payment details and never places an order.
"""
from __future__ import annotations

import base64
import re

from .fetcher import BROWSER_UA

ADD_RE = re.compile(r"add to (cart|bag|basket|trolley)|buy now|add$", re.I)
CHECKOUT_RE = re.compile(r"check ?out|proceed to (buy|pay|checkout)|continue to checkout|place order", re.I)


def run(ctx) -> dict:
    if "browser" in ctx.shared:
        return ctx.shared["browser"]
    out: dict = {"renders": {}, "task": None, "error": None}
    ctx.shared["browser"] = out
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        out["error"] = "Playwright is not installed (pip install playwright && playwright install chromium)."
        return out
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(user_agent=BROWSER_UA, viewport={"width": 1280, "height": 900})
            for u in ctx.pages.products[:2]:
                try:
                    page.goto(u, wait_until="domcontentloaded", timeout=30000)
                    _settle(page)
                    out["renders"][u] = page.inner_text("body")[:50000]
                except PWTimeout:
                    out["renders"][u] = None
            out["task"] = _task_probe(ctx, page, PWTimeout)
            browser.close()
    except Exception as e:  # browser binary missing, crash, etc.
        out["error"] = f"Browser run failed: {type(e).__name__}: {e}"[:300]
    return out


def _settle(page, ms: int = 2500):
    try:
        page.wait_for_load_state("networkidle", timeout=ms + 2000)
    except Exception:
        page.wait_for_timeout(ms)


def _first_visible(locators):
    for loc in locators:
        try:
            n = min(loc.count(), 5)
        except Exception:
            continue
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
    return None


def _task_probe(ctx, page, PWTimeout) -> dict:
    steps = []
    stage = 0  # 0 none, 1 product loaded, 2 add control found, 3 item in cart, 4 checkout reached
    shot = None
    for u in ctx.pages.products[:3]:
        try:
            page.goto(u, wait_until="domcontentloaded", timeout=30000)
            _settle(page)
        except PWTimeout:
            steps.append(f"Timed out loading {u}")
            continue
        stage = max(stage, 1)
        btn = _first_visible([
            page.get_by_role("button", name=ADD_RE),
            page.locator("input[type=submit][value*='Add' i]"),
            page.locator("button[name='add'], [data-testid*='add-to-cart' i], [id*='add-to-cart' i]"),
        ])
        if not btn:
            steps.append(f"No add-to-cart control found on {u}")
            continue
        stage = max(stage, 2)
        steps.append(f"Found add-to-cart control on {u}")
        try:
            btn.click(timeout=8000)
            _settle(page)
            steps.append("Clicked add to cart")
        except Exception as e:
            steps.append(f"Add-to-cart click failed: {type(e).__name__}")
            continue
        cart = ctx.pages.cart or ctx.abs("/cart")
        try:
            page.goto(cart, wait_until="domcontentloaded", timeout=30000)
            _settle(page)
        except PWTimeout:
            steps.append("Cart page timed out")
            break
        co = _first_visible([page.get_by_role("button", name=CHECKOUT_RE),
                             page.get_by_role("link", name=CHECKOUT_RE)])
        if not co:
            steps.append("Cart shows no checkout control (item may not have been added)")
            shot = _shot(page)
            break
        stage = max(stage, 3)
        steps.append("Cart has a checkout control")
        try:
            co.click(timeout=8000)
            _settle(page, 3500)
        except Exception as e:
            steps.append(f"Checkout click failed: {type(e).__name__}")
            shot = _shot(page)
            break
        form = page.locator("input[type=email], input[autocomplete*='email'], input[name*='email' i], "
                            "input[autocomplete*='address'], input[name*='address' i]")
        login = page.locator("input[type=password]")
        if _first_visible([form]):
            stage = 4
            steps.append(f"Reached checkout form at {page.url} (stopped before entering details)")
        elif _first_visible([login]):
            stage = 3
            steps.append(f"Checkout requires sign-in at {page.url}; guest agents stop here")
        else:
            steps.append(f"Checkout click landed on {page.url} without a recognisable form")
        shot = _shot(page)
        break
    return {"stage": stage, "steps": steps, "screenshot": shot}


def _shot(page) -> str | None:
    try:
        png = page.screenshot(type="jpeg", quality=55, full_page=False)
        return "data:image/jpeg;base64," + base64.b64encode(png).decode()
    except Exception:
        return None
