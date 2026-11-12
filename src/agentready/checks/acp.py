"""Layer: Agentic Commerce Protocol (ACP) signals.

ACP (OpenAI and Stripe) is integrated merchant-by-merchant and has no public
discovery file, so compliance cannot be verified from outside. We report
signals only (status INFO, never scored) and say so in the report.
"""
from __future__ import annotations

import re

from ..models import CheckResult, Status
from . import check

PLATFORMS = {
    "Shopify": re.compile(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", re.I),
    "Salesforce Commerce Cloud": re.compile(r"demandware|/on/demandware\.store|dwanalytics", re.I),
    "Adobe Commerce (Magento)": re.compile(r"Magento_|mage/cookies|static/version\d+/frontend", re.I),
    "BigCommerce": re.compile(r"cdn\d*\.bigcommerce\.com|bigcommerce", re.I),
    "WooCommerce": re.compile(r"woocommerce", re.I),
    "commercetools": re.compile(r"commercetools", re.I),
    "SAP Commerce": re.compile(r"hybris|/_ui/responsive/", re.I),
    "VTEX": re.compile(r"vtexassets|vteximg|\.vtex\.", re.I),
}


@check
def acp_signals(ctx):
    res = CheckResult("acp-signals", "acp", "ACP readiness signals (inferred)", Status.INFO, weight=0)
    pages = [ctx.pages.home] + ctx.pages.products[:2]
    html = " ".join((ctx.get(u).text or "")[:600000] for u in pages)
    platform = next((n for n, rx in PLATFORMS.items() if rx.search(html)), None)
    ctx.shared["platform"] = platform
    stripe = bool(re.search(r"js\.stripe\.com|stripe\.com/v3", html, re.I))
    signals = []
    if platform:
        signals.append(f"Commerce platform appears to be {platform}. Check whether the platform offers "
                       "native ACP or UCP enablement; this is often the fastest route.")
    if stripe:
        signals.append("Stripe.js is loaded. ACP's reference payment path runs on Stripe, which shortens integration.")
    res.evidence = signals or ["No platform or payment signals detected."]
    res.summary = ("ACP has no public discovery endpoint, so participation can't be confirmed from outside. "
                   "Confirm with the client whether they're live in ChatGPT checkout.")
    res.data = {"platform": platform, "stripe": stripe}
    return res
