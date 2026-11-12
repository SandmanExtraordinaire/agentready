"""Layer: structured data that answer engines and agents rely on (AEO/GEO)."""
from __future__ import annotations

from ..context import types_of
from ..models import CheckResult, Status, status_for
from .rendering import prices_in
from . import check

# field -> (weight, label)
PRODUCT_FIELDS = {
    "name": (1.0, "name"),
    "image": (1.0, "image"),
    "price": (1.0, "price"),
    "currency": (1.0, "currency"),
    "availability": (1.0, "availability"),
    "identifier": (1.0, "GTIN/SKU/MPN"),
    "brand": (0.5, "brand"),
    "description": (0.5, "description"),
    "rating": (0.5, "ratings"),
    "returns": (0.75, "return policy"),
    "shipping": (0.75, "shipping details"),
}


def _as_list(x):
    return x if isinstance(x, list) else ([x] if x else [])


def product_nodes(nodes: list[dict]) -> list[dict]:
    out = []
    for n in nodes:
        t = types_of(n)
        if "Product" in t or "ProductGroup" in t:
            out.append(n)
            out.extend(v for v in _as_list(n.get("hasVariant")) if isinstance(v, dict))
    return out


def product_fields(p: dict) -> dict[str, bool]:
    offers = [o for o in _as_list(p.get("offers")) if isinstance(o, dict)]
    # AggregateOffer may nest offers
    for o in list(offers):
        offers += [x for x in _as_list(o.get("offers")) if isinstance(x, dict)]
    def any_offer(*keys):
        return any(o.get(k) not in (None, "", []) for o in offers for k in keys)
    return {
        "name": bool(p.get("name")),
        "image": bool(p.get("image")),
        "price": any_offer("price", "lowPrice") or any(
            isinstance(o.get("priceSpecification"), (dict, list)) for o in offers),
        "currency": any_offer("priceCurrency") or any(
            "priceCurrency" in str(o.get("priceSpecification", "")) for o in offers),
        "availability": any_offer("availability"),
        "identifier": any(p.get(k) for k in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "sku", "mpn")),
        "brand": bool(p.get("brand")),
        "description": bool(p.get("description")),
        "rating": bool(p.get("aggregateRating")),
        "returns": bool(p.get("hasMerchantReturnPolicy")) or any_offer("hasMerchantReturnPolicy"),
        "shipping": any_offer("shippingDetails"),
    }


def jsonld_prices(prods: list[dict]) -> set[float]:
    vals = set()
    for p in prods:
        for o in _as_list(p.get("offers")):
            if not isinstance(o, dict):
                continue
            for k in ("price", "lowPrice", "highPrice"):
                try:
                    vals.add(round(float(str(o.get(k)).replace(",", "")), 2))
                except (TypeError, ValueError):
                    pass
    return vals


@check
def product_schema(ctx):
    res = CheckResult("product-schema", "aeo", "Product structured data (schema.org)", Status.SKIP, weight=4.0)
    if not ctx.pages.products:
        res.summary = "No product pages to test."
        return res
    total_w = sum(w for w, _ in PRODUCT_FIELDS.values())
    per_page, missing_count = [], {k: 0 for k in PRODUCT_FIELDS}
    for u in ctx.pages.products:
        prods = product_nodes(ctx.jsonld(u))
        if not prods:
            soup = ctx.soup(u)
            micro = soup is not None and soup.find(attrs={"itemtype": lambda v: v and "schema.org/Product" in v})
            per_page.append(0.3 if micro else 0.0)
            res.evidence.append(f"{u}: no Product JSON-LD" + (" (microdata only)" if micro else ""))
            for k in missing_count:
                missing_count[k] += 1
            continue
        merged = {k: any(product_fields(p)[k] for p in prods) for k in PRODUCT_FIELDS}
        s = sum(PRODUCT_FIELDS[k][0] for k, ok in merged.items() if ok) / total_w
        per_page.append(s)
        miss = [PRODUCT_FIELDS[k][1] for k, ok in merged.items() if not ok]
        for k, ok in merged.items():
            missing_count[k] += not ok
        res.evidence.append(f"{u}: Product JSON-LD, {s:.0%} complete"
                            + (f"; missing {', '.join(miss)}" if miss else ""))
    score = sum(per_page) / len(per_page)
    res.score, res.status = score, status_for(score)
    res.data = {"missing_by_field": missing_count, "pages": len(per_page)}
    gaps = [PRODUCT_FIELDS[k][1] for k, n in missing_count.items() if n]
    res.summary = ("Product markup is complete." if not gaps
                   else f"Product markup gaps: {', '.join(gaps)}.")
    if gaps:
        res.fix = ("Emit Product JSON-LD in the server HTML with offers (price, priceCurrency, availability), "
                   "a GTIN, brand, aggregateRating, hasMerchantReturnPolicy and shippingDetails. Agents compare "
                   "on exactly these fields.")
    return res


@check
def price_consistency(ctx):
    res = CheckResult("price-consistency", "aeo", "Markup price matches the visible price", Status.SKIP, weight=2.0)
    raw = ctx.shared.get("raw_text", {})
    checked, matched = 0, 0
    for u in ctx.pages.products:
        declared = jsonld_prices(product_nodes(ctx.jsonld(u)))
        shown = prices_in(raw.get(u, ""))
        if not declared or not shown:
            continue
        checked += 1
        if declared & shown:
            matched += 1
        else:
            res.evidence.append(f"{u}: markup says {sorted(declared)[:3]}, page shows {sorted(shown)[:3]}")
    if not checked:
        res.summary = "Not enough data (needs both a markup price and a visible price)."
        return res
    score = matched / checked
    res.score, res.status = score, status_for(score)
    res.summary = f"{matched} of {checked} product pages show the same price as their markup."
    if matched < checked:
        res.fix = ("Generate JSON-LD prices from the same source as the rendered price. Mismatches make "
                   "answer engines distrust or drop the listing.")
    return res


@check
def site_entities(ctx):
    res = CheckResult("site-entities", "aeo", "Organization and site search markup", Status.FAIL, weight=1.5)
    nodes = ctx.jsonld(ctx.pages.home)
    org = next((n for n in nodes if types_of(n) & {"Organization", "OnlineStore", "Corporation", "Brand"}), None)
    site = next((n for n in nodes if "WebSite" in types_of(n)), None)
    search = bool(site and site.get("potentialAction"))
    parts = {"Organization": org is not None, "logo": bool(org and org.get("logo")),
             "sameAs profiles": bool(org and org.get("sameAs")), "WebSite": site is not None,
             "site search action": search}
    score = sum(parts.values()) / len(parts)
    res.score, res.status = score, status_for(score)
    have = [k for k, v in parts.items() if v]
    miss = [k for k, v in parts.items() if not v]
    res.summary = f"Homepage declares: {', '.join(have) or 'nothing'}."
    if miss:
        res.evidence.append("Missing: " + ", ".join(miss))
        res.fix = ("Add Organization (name, logo, sameAs) and WebSite with a SearchAction on the homepage, "
                   "so agents can identify the brand and run on-site searches directly.")
    return res


@check
def page_meta(ctx):
    res = CheckResult("page-meta", "aeo", "Canonical, meta and Open Graph tags", Status.SKIP, weight=1.0)
    pages = ctx.pages.products[:3] or [ctx.pages.home]
    scores = []
    for u in pages:
        s = ctx.soup(u)
        if s is None:
            continue
        checks = {
            "canonical": s.find("link", rel=lambda r: r and "canonical" in r) is not None,
            "meta description": s.find("meta", attrs={"name": "description"}) is not None,
            "og:title": s.find("meta", property="og:title") is not None,
            "og:image": s.find("meta", property="og:image") is not None,
            "breadcrumbs": any("BreadcrumbList" in types_of(n) for n in ctx.jsonld(u)),
        }
        scores.append(sum(checks.values()) / len(checks))
        miss = [k for k, v in checks.items() if not v]
        if miss:
            res.evidence.append(f"{u}: missing {', '.join(miss)}")
    if not scores:
        return res
    score = sum(scores) / len(scores)
    res.score, res.status = score, status_for(score)
    res.summary = "Page-level metadata is in place." if res.status == Status.PASS else "Page metadata is incomplete."
    if res.status != Status.PASS:
        res.fix = "Add canonical URLs, meta descriptions, og:title/og:image and BreadcrumbList on product pages."
    return res


@check
def sitemap(ctx):
    res = CheckResult("sitemap", "aeo", "XML sitemap", Status.FAIL, weight=1.0)
    if ctx.sitemap_urls:
        res.status, res.score = Status.PASS, 1.0
        res.summary = f"Found {len(ctx.sitemap_urls)} sitemap file(s)."
        res.evidence = ctx.sitemap_urls[:5]
    else:
        res.summary = "No sitemap found in robots.txt or at /sitemap.xml."
        res.fix = "Publish a sitemap with product URLs and reference it from robots.txt."
    return res
