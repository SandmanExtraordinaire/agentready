"""Layer 5 — does the content exist without JavaScript?

Most AI fetchers read raw HTML and do not run JavaScript. If the price only
appears after scripts run, the store is effectively invisible to them."""
from __future__ import annotations

from ..models import Finding, Status
from . import ScanContext, check
from ..models import Page
from .discoverability import find, price_variants, visible_text


@check("rendering")
def raw_html(ctx: ScanContext) -> list[Finding]:
    pages = [p for p in ctx.pages() if p.html and p.kind in ("product", "category", "home")]
    facts = ctx.shared.get("product_facts", {})
    ev, good, judged = [], 0, 0
    for p in pages:
        text = visible_text(p.html)
        f = facts.get(p.url)
        if p.kind == "product" and f and (f.get("name") or f.get("price")):
            judged += 1
            name_ok = bool(f.get("name")) and str(f["name"])[:40].lower() in text.lower()
            price_ok = f.get("price") is None or any(v in text for v in price_variants(f["price"]))
            ok = name_ok and price_ok
            good += ok
            ev.append(f"{'✓' if ok else '✗'} {p.url}: name {'in' if name_ok else 'NOT in'} raw HTML, "
                      f"price {'in' if price_ok else 'NOT in'} raw HTML")
        else:
            judged += 1
            ok = len(text) > 1500
            good += ok
            ev.append(f"{'✓' if ok else '✗'} {p.url}: {len(text):,} characters of text without JavaScript")
    if not judged:
        return [Finding("raw_html", "rendering", "Content is readable without JavaScript", Status.SKIP,
                        "No pages to evaluate.")]
    ratio = good / judged
    status = Status.PASS if ratio >= 0.999 else Status.PARTIAL if ratio >= 0.5 else Status.FAIL
    return [Finding("raw_html", "rendering", "Content is readable without JavaScript", status,
                    f"{good} of {judged} key pages show their core content in the raw HTML.", ev,
                    fix="Server-render (SSR/SSG) product name, price, availability and JSON-LD; "
                        "don't inject them client-side.")]


@check("rendering")
def js_injected_markup(ctx: ScanContext) -> list[Finding]:
    title = "Structured data does not depend on JavaScript"
    if ctx.browser is None:
        return [Finding("js_markup", "rendering", title, Status.SKIP,
                        "Headless browser not available; install the [browser] extra to run this check.",
                        [ctx.browser_error] if ctx.browser_error else [])]
    ev, injected, compared = [], 0, 0
    for p in [p for p in ctx.pages("product") if p.html][:3]:
        raw_products = len(find(p, "Product", "ProductGroup"))
        try:
            html, text = ctx.browser.render(p.url)
        except Exception as e:
            ev.append(f"{p.url}: render failed ({type(e).__name__})")
            continue
        rendered = Page(url=p.url, kind="product", html=html)
        rendered_products = len(find(rendered, "Product", "ProductGroup"))
        raw_len, rendered_len = len(visible_text(p.html)), len(text)
        compared += 1
        if rendered_products and not raw_products:
            injected += 1
            ev.append(f"✗ {p.url}: Product markup appears only after JavaScript runs")
        else:
            ev.append(f"✓ {p.url}: markup in raw HTML ({raw_products} Product node(s)); "
                      f"text {raw_len:,} raw vs {rendered_len:,} rendered chars")
    if not compared:
        return [Finding("js_markup", "rendering", title, Status.SKIP, "Product pages could not be rendered.", ev)]
    return [Finding("js_markup", "rendering", title,
                    Status.PASS if not injected else Status.FAIL if injected == compared else Status.PARTIAL,
                    "Product markup is present before JavaScript runs." if not injected
                    else f"On {injected} of {compared} pages, Product markup is injected by JavaScript.",
                    ev, fix="" if not injected else "Render JSON-LD on the server; most AI fetchers never see JS-injected markup.")]
