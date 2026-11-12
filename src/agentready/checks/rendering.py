"""Layer: is the content there for agents that don't run JavaScript?"""
from __future__ import annotations

import copy
import re

from .. import browser
from ..models import CheckResult, Status, status_for
from . import check

PRICE_RE = re.compile(
    r"(?:₹|rs\.?|inr|\$|usd|€|eur|£|gbp|aed|sgd|aud)\s?(\d{1,3}(?:[,\s]\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"|(\d{1,3}(?:[,\s]\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(?:₹|inr|usd|eur|gbp|€)", re.I)


def visible_text(soup) -> str:
    if soup is None:
        return ""
    s = copy.copy(soup)  # never mutate the cached soup
    for t in s(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    return re.sub(r"\s+", " ", s.get_text(" ")).strip()


def prices_in(text: str) -> set[float]:
    vals = set()
    for m in PRICE_RE.finditer(text):
        raw = (m.group(1) or m.group(2) or "").replace(",", "").replace(" ", "")
        try:
            vals.add(round(float(raw), 2))
        except ValueError:
            pass
    return vals


@check
def raw_html_content(ctx):
    res = CheckResult("raw-html-content", "rendering", "Product content present without JavaScript",
                      Status.SKIP, weight=3.0)
    pdps = ctx.pages.products
    if not pdps:
        res.summary = "No product pages to test."
        return res
    scores, texts = [], {}
    for u in pdps:
        soup = ctx.soup(u)
        if soup is None:
            res.evidence.append(f"{u}: could not load raw HTML")
            scores.append(0.0)
            continue
        text = visible_text(soup)
        texts[u] = text
        h1 = soup.find("h1") is not None
        price = bool(prices_in(text))
        enough = len(text) >= 400
        s = 0.4 * enough + 0.2 * h1 + 0.4 * price
        scores.append(s)
        missing = [n for n, ok in (("descriptive text", enough), ("an H1 title", h1), ("a price", price)) if not ok]
        res.evidence.append(f"{u}: {len(text):,} chars of text"
                            + (f"; missing {', '.join(missing)}" if missing else "; title, text and price present"))
    ctx.shared["raw_text"] = texts

    if ctx.use_browser:
        b = browser.run(ctx)
        for u, rendered in b["renders"].items():
            if rendered and texts.get(u) is not None:
                ratio = len(texts[u]) / max(len(rendered), 1)
                res.evidence.append(f"{u}: raw HTML holds {min(ratio, 1):.0%} of the rendered text")
                if ratio < 0.5:
                    idx = pdps.index(u)
                    scores[idx] = min(scores[idx], 0.3)

    score = sum(scores) / len(scores)
    res.score, res.status = score, status_for(score)
    res.summary = ("Product pages are readable as plain HTML." if res.status == Status.PASS else
                   "Some product content only appears after JavaScript runs, so many agents can't see it.")
    if res.status != Status.PASS:
        res.fix = ("Server-render product title, description, price and availability (SSR or pre-rendering). "
                   "Most AI fetchers read raw HTML and don't execute JavaScript.")
    return res
