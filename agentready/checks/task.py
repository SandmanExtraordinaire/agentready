"""Layer 6 — can an agent actually get from product page to checkout?

The browser probe adds one item to the cart and opens checkout, then stops.
It never enters personal details, never submits a form and never pays."""
from __future__ import annotations

import re

from ..agents import AGENTS
from ..models import Finding, Status
from . import ScanContext, check
from .access import BLOCK_CODES

ADD_RE = re.compile(r"add\s+to\s+(cart|bag|basket|trolley)|buy\s+now|add\s+item", re.I)
CHECKOUT_RE = re.compile(r"(proceed\s+to\s+)?check\s*out|secure\s+checkout|continue\s+to\s+checkout", re.I)
GUEST_RE = re.compile(r"guest|continue\s+without|email\s+address|contact\s+information|express\s+checkout", re.I)
CART_PATHS = ["/cart", "/basket", "/bag", "/checkout/cart"]


@check("task")
def cart_for_agents(ctx: ScanContext) -> list[Finding]:
    """Without a browser: can a user-initiated agent load the cart page at all?"""
    agent = next(a for a in AGENTS if a.token == "ChatGPT-User")
    rows, reachable = [], None
    for path in CART_PATHS:
        r = ctx.fetcher.get(ctx.base + path, ua=agent.ua, accept="text/html")
        rows.append(f"{path} as {agent.token}: {r.status or r.error}")
        if r.status == 404:
            continue
        reachable = r.ok and not r.looks_like_challenge()
        blocked = r.status in BLOCK_CODES or r.looks_like_challenge()
        if reachable or blocked:
            break
    if reachable is None:
        return [Finding("cart_access", "task", "Cart is reachable by assistant agents", Status.SKIP,
                        "No cart page found at common paths.", rows)]
    return [Finding("cart_access", "task", "Cart is reachable by assistant agents",
                    Status.PASS if reachable else Status.FAIL,
                    "An assistant agent can load the cart page." if reachable
                    else "The cart page blocks or challenges assistant agents.", rows,
                    fix="" if reachable else "Allow verified user-initiated agents on cart and checkout paths.",
                    confidence="inferred")]


def _try_select_variants(page) -> None:
    for sel in page.locator("select:visible").all()[:4]:
        try:
            opts = [o for o in sel.locator("option").all() if o.get_attribute("value") and not o.is_disabled()]
            if len(opts) > 1:
                sel.select_option(opts[1].get_attribute("value"))
        except Exception:
            pass
    for group in page.locator("fieldset:visible").all()[:4]:
        try:
            radio = group.locator("input[type=radio]:not([disabled])").first
            if radio.count():
                radio.check(force=True)
        except Exception:
            pass


@check("task")
def journey(ctx: ScanContext) -> list[Finding]:
    titles = {"task_add_to_cart": "An agent can add a product to the cart",
              "task_checkout": "An agent can reach checkout"}
    products = [p for p in ctx.pages("product") if p.html]
    if ctx.browser is None or not products:
        why = ("Headless browser not available; install the [browser] extra to run the journey probe."
               if ctx.browser is None else "No product page to start from.")
        return [Finding(fid, "task", t, Status.SKIP, why, [ctx.browser_error] if ctx.browser_error else [])
                for fid, t in titles.items()]

    ev, added, checkout_status, checkout_note = [], False, Status.FAIL, "Checkout was not reached."
    for prod in products[:2]:
        page = ctx.browser.new_page()
        try:
            page.goto(prod.url, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            _try_select_variants(page)
            btn = page.get_by_role("button", name=ADD_RE).first
            if not btn.count():
                btn = page.locator("button[name=add], [data-testid*=add-to-cart i], form[action*=cart] [type=submit]").first
            if not btn.count():
                ev.append(f"{prod.url}: no add-to-cart button found")
                continue
            btn.click()
            page.wait_for_timeout(2500)
            ev.append(f"{prod.url}: clicked '{(btn.inner_text() or '').strip()[:40]}'")
            for path in CART_PATHS:
                resp = page.goto(ctx.base + path, wait_until="domcontentloaded")
                if resp and resp.status != 404:
                    break
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            empty = re.search(r"(cart|bag|basket) is empty|no items", body, re.I)
            if empty:
                ev.append(f"Cart page says it is empty ({page.url})")
                continue
            added = True
            ev.append(f"Cart has an item ({page.url})")
            go = page.get_by_role("button", name=CHECKOUT_RE).first
            if not go.count():
                go = page.get_by_role("link", name=CHECKOUT_RE).first
            if not go.count():
                checkout_status, checkout_note = Status.FAIL, "Cart has no checkout button an agent can identify."
                break
            go.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2500)
            text = page.inner_text("body")
            ev.append(f"Checkout opened at {page.url}")
            if GUEST_RE.search(text) or page.locator("input[type=email]").count():
                checkout_status, checkout_note = Status.PASS, "Checkout opens and allows guest or express checkout."
            elif page.locator("input[type=password]").count():
                checkout_status, checkout_note = Status.PARTIAL, "Checkout requires signing in; an agent needs delegated identity."
            else:
                checkout_status, checkout_note = Status.PARTIAL, "Checkout opened, but the next step is unclear to an agent."
            break
        except Exception as e:
            ev.append(f"{prod.url}: probe stopped ({type(e).__name__}: {str(e).splitlines()[0][:120]})")
        finally:
            page.context.close()

    return [
        Finding("task_add_to_cart", "task", titles["task_add_to_cart"], Status.PASS if added else Status.FAIL,
                "A headless agent added a product to the cart." if added
                else "A headless agent could not add a product to the cart.", ev,
                fix="" if added else "Use standard <button> elements with clear labels ('Add to cart') and avoid "
                                     "bot challenges on add-to-cart requests.", confidence="verified"),
        Finding("task_checkout", "task", titles["task_checkout"], checkout_status if added else Status.FAIL,
                checkout_note if added else "Not attempted: nothing in the cart.", [],
                fix="" if checkout_status == Status.PASS else "Offer guest checkout and label the checkout action clearly; "
                                                                "for signed-in flows, support UCP identity linking."),
    ]
