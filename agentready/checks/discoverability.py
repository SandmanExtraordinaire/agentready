"""Layer 4 — can AI answer engines understand and cite the catalogue (AEO/GEO)?"""
from __future__ import annotations

import re
from typing import Any, Iterator

import extruct
from bs4 import BeautifulSoup

from ..models import Finding, Page, Status
from . import ScanContext, check

ID_FIELDS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn", "isbn")


# ---------- structured-data helpers ----------

def _types(node: dict) -> list[str]:
    t = node.get("@type") or node.get("type") or []
    t = t if isinstance(t, list) else [t]
    return [str(x).rsplit("/", 1)[-1] for x in t]


def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        if "@graph" in obj:
            yield from _walk(obj["@graph"])
        yield obj
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x)


def _microdata_to_ld(item: dict) -> dict:
    out = {"@type": item.get("type")}
    for k, v in (item.get("properties") or {}).items():
        out[k] = _microdata_to_ld(v) if isinstance(v, dict) and "properties" in v else v
    return out


def structured(page: Page) -> list[dict]:
    """All schema.org nodes on a page (JSON-LD and microdata), cached on the page."""
    cache = getattr(page, "_sd", None)
    if cache is not None:
        return cache
    nodes: list[dict] = []
    if page.html:
        try:
            data = extruct.extract(page.html, base_url=page.final_url or page.url,
                                   syntaxes=["json-ld", "microdata"], errors="ignore", uniform=False)
            nodes += list(_walk(data.get("json-ld", [])))
            nodes += [_microdata_to_ld(i) for i in data.get("microdata", [])]
        except Exception:
            pass
    page._sd = nodes  # type: ignore[attr-defined]
    return nodes


def find(page: Page, *types: str) -> list[dict]:
    return [n for n in structured(page) if any(t in types for t in _types(n))]


def _first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def offers_of(product: dict) -> list[dict]:
    offers = product.get("offers")
    if offers is None and "hasVariant" in product:   # ProductGroup
        offers = [o for v in _as_list(product["hasVariant"]) if isinstance(v, dict) for o in _as_list(v.get("offers"))]
    out = []
    for o in _as_list(offers):
        if isinstance(o, dict):
            out.append(o)
            out += [x for x in _as_list(o.get("offers")) if isinstance(x, dict)]   # AggregateOffer
    return out


def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else ([] if v is None else [v])


def price_of(offer: dict) -> Any:
    for key in ("price", "lowPrice"):
        if offer.get(key) not in (None, ""):
            return offer[key]
    spec = _first(offer.get("priceSpecification"))
    return spec.get("price") if isinstance(spec, dict) else None


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    return " ".join(soup.get_text(" ").split())


def price_variants(price: Any) -> list[str]:
    try:
        v = float(str(price).replace(",", ""))
    except ValueError:
        return [str(price)]
    whole = f"{v:,.0f}"
    variants = {f"{v:,.2f}", f"{v:.2f}", whole, whole.replace(",", "."), f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")}
    if v == int(v):
        variants |= {str(int(v)), f"{int(v):,}"}
    return sorted(variants, key=len, reverse=True)


def _grade(ratio: float) -> Status:
    return Status.PASS if ratio >= 0.999 else Status.PARTIAL if ratio > 0 else Status.FAIL


# ---------- checks ----------

@check("discoverability")
def product_data(ctx: ScanContext) -> list[Finding]:
    pages = [p for p in ctx.pages("product") if p.html]
    if not pages:
        msg = "No product pages could be scanned."
        return [Finding(fid, "discoverability", title, Status.SKIP, msg,
                        fix="Re-run with --product-url pointing at a few product pages.")
                for fid, title in [("product_schema", "Product pages carry Product markup"),
                                   ("offer_fields", "Price, currency and availability are machine-readable"),
                                   ("identifiers", "Products have GTIN/MPN and brand"),
                                   ("policies", "Return and shipping policies are machine-readable"),
                                   ("reviews", "Ratings are machine-readable"),
                                   ("price_consistency", "Marked-up price matches the visible price")]]

    with_product, field_scores, ids, policies, ratings, consistent, priced = 0, [], [], [], 0, 0, 0
    ev_schema, ev_fields, ev_ids, ev_pol, ev_price = [], [], [], [], []
    ctx.shared["product_facts"] = {}
    org_policy = any(n.get("hasMerchantReturnPolicy") for p in ctx.pages() for n in find(p, "Organization", "OnlineStore"))

    for p in pages:
        prods = find(p, "Product", "ProductGroup", "IndividualProduct")
        if not prods:
            ev_schema.append(f"✗ {p.url}: no Product markup")
            field_scores.append(0.0)
            ids.append(0.0)
            policies.append(0.0)
            continue
        with_product += 1
        prod = max(prods, key=lambda n: len(n))
        offers = offers_of(prod)
        offer = offers[0] if offers else {}
        price = price_of(offer)
        name = _first(prod.get("name"))
        ctx.shared["product_facts"][p.url] = {"name": name, "price": price}
        checks = {
            "name": bool(name), "image": bool(prod.get("image")), "description": bool(prod.get("description")),
            "price": price not in (None, ""),
            "currency": bool(offer.get("priceCurrency") or (_first(offer.get("priceSpecification")) or {}).get("priceCurrency")),
            "availability": bool(offer.get("availability")),
        }
        field_scores.append(sum(checks.values()) / len(checks))
        missing = [k for k, v in checks.items() if not v]
        ev_schema.append(f"✓ {p.url}: {', '.join(sorted(set(_types(prod))))}")
        ev_fields.append(f"{p.url}: missing {', '.join(missing)}" if missing else f"{p.url}: complete")

        has_id = any(prod.get(k) or offer.get(k) for k in ID_FIELDS)
        has_brand = bool(prod.get("brand"))
        has_sku = bool(prod.get("sku") or offer.get("sku"))
        ids.append(1.0 if has_id and has_brand else 0.5 if (has_id or has_brand or has_sku) else 0.0)
        ev_ids.append(f"{p.url}: GTIN/MPN {'yes' if has_id else 'no'}, brand {'yes' if has_brand else 'no'}, SKU {'yes' if has_sku else 'no'}")

        has_return = org_policy or any(o.get("hasMerchantReturnPolicy") for o in offers) or bool(prod.get("hasMerchantReturnPolicy"))
        has_ship = any(o.get("shippingDetails") for o in offers)
        policies.append((has_return + has_ship) / 2)
        ev_pol.append(f"{p.url}: returns {'yes' if has_return else 'no'}, shipping {'yes' if has_ship else 'no'}")

        ratings += bool(prod.get("aggregateRating"))

        if price not in (None, ""):
            priced += 1
            text = visible_text(p.html)
            hit = any(v in text for v in price_variants(price))
            consistent += hit
            ev_price.append(f"{'✓' if hit else '✗'} {p.url}: marked-up price {price} {'found' if hit else 'not found'} in visible text")

    n = len(pages)
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    out = [
        Finding("product_schema", "discoverability", "Product pages carry Product markup", _grade(with_product / n),
                f"{with_product} of {n} product pages have schema.org Product markup.", ev_schema,
                fix="Add JSON-LD Product markup (server-rendered) to every product template."),
        Finding("offer_fields", "discoverability", "Price, currency and availability are machine-readable",
                _grade(avg(field_scores)) if avg(field_scores) < 0.999 else Status.PASS,
                f"Average completeness of core product fields: {avg(field_scores):.0%}.", ev_fields,
                fix="Include name, image, description, offers.price, offers.priceCurrency and offers.availability."),
        Finding("identifiers", "discoverability", "Products have GTIN/MPN and brand", _grade(avg(ids)),
                f"Identifier coverage: {avg(ids):.0%}. Agents use GTINs to match the same product across stores.",
                ev_ids, fix="Add gtin13 (or gtin/mpn) and brand to Product markup."),
        Finding("policies", "discoverability", "Return and shipping policies are machine-readable", _grade(avg(policies)),
                f"Policy coverage: {avg(policies):.0%}. Agents compare total cost and return terms before recommending.",
                ev_pol, fix="Add MerchantReturnPolicy (on Organization or offers) and OfferShippingDetails."),
        Finding("reviews", "discoverability", "Ratings are machine-readable", _grade(ratings / n),
                f"{ratings} of {n} product pages expose aggregateRating.",
                fix="Expose aggregateRating where reviews exist."),
    ]
    if priced:
        out.append(Finding("price_consistency", "discoverability", "Marked-up price matches the visible price",
                           _grade(consistent / priced), f"{consistent} of {priced} marked-up prices appear on the page.",
                           ev_price, fix="Keep JSON-LD prices in sync with the displayed price; mismatches erode agent trust."))
    else:
        out.append(Finding("price_consistency", "discoverability", "Marked-up price matches the visible price",
                           Status.SKIP, "No marked-up prices to compare."))
    return out


@check("discoverability")
def organisation(ctx: ScanContext) -> list[Finding]:
    home = ctx.pages("home")
    nodes = find(home[0], "Organization", "OnlineStore", "Corporation", "LocalBusiness", "Store") if home else []
    if not nodes:
        return [Finding("organization", "discoverability", "Brand identity is machine-readable", Status.FAIL,
                        "No Organization markup on the homepage.",
                        fix="Add Organization (or OnlineStore) JSON-LD with name, url, logo and sameAs profiles.")]
    org = nodes[0]
    have = [k for k in ("name", "url", "logo", "sameAs") if org.get(k)]
    return [Finding("organization", "discoverability", "Brand identity is machine-readable",
                    Status.PASS if len(have) == 4 else Status.PARTIAL,
                    f"Organization markup found with: {', '.join(have)}.",
                    fix="" if len(have) == 4 else "Add the missing fields: " + ", ".join(k for k in ("name", "url", "logo", "sameAs") if k not in have))]


@check("discoverability")
def crawl_aids(ctx: ScanContext) -> list[Finding]:
    d = ctx.discovery
    out = []
    if d.sitemaps:
        prod = sum(1 for p in ctx.pages("product"))
        out.append(Finding("sitemap", "discoverability", "Sitemap lists the catalogue",
                           Status.PASS if prod else Status.PARTIAL,
                           f"{len(d.sitemaps)} sitemap file(s), {d.sitemap_url_count:,} URLs read.",
                           d.sitemaps[:6], fix="" if prod else "Include product URLs in the sitemap."))
    else:
        out.append(Finding("sitemap", "discoverability", "Sitemap lists the catalogue", Status.FAIL,
                           "No sitemap found in robots.txt or at /sitemap.xml.",
                           fix="Publish an XML sitemap and reference it from robots.txt."))

    r = ctx.fetcher.get(ctx.base + "/llms.txt", accept="text/plain")
    is_text = r.ok and "<html" not in r.text[:500].lower() and len(r.text.strip()) > 20
    out.append(Finding("llms_txt", "discoverability", "llms.txt guide for AI", Status.PASS if is_text else Status.FAIL,
                       "llms.txt is published." if is_text else "No llms.txt found.",
                       [f"{r.url} → {r.status or r.error}"],
                       fix="" if is_text else "Optional, low effort: publish /llms.txt pointing to key categories, policies and help pages. Adoption by AI vendors is still uneven.",
                       ))

    pages = [p for p in ctx.pages() if p.html and p.kind in ("product", "category")]
    scores, ev = [], []
    for p in pages:
        soup = BeautifulSoup(p.html, "lxml")
        have = {
            "title": bool(soup.title and soup.title.get_text(strip=True)),
            "meta description": bool(soup.find("meta", attrs={"name": re.compile("^description$", re.I)})),
            "canonical": bool(soup.find("link", rel=lambda v: v and "canonical" in v)),
            "og:title": bool(soup.find("meta", property="og:title")),
            "og:image": bool(soup.find("meta", property="og:image")),
            "breadcrumbs": bool(find(p, "BreadcrumbList")),
        }
        scores.append(sum(have.values()) / len(have))
        miss = [k for k, v in have.items() if not v]
        ev.append(f"{p.url}: " + (f"missing {', '.join(miss)}" if miss else "complete"))
    ratio = sum(scores) / len(scores) if scores else 0
    out.append(Finding("page_meta", "discoverability", "Pages have titles, descriptions, canonicals and breadcrumbs",
                       _grade(ratio) if scores else Status.SKIP, f"Metadata completeness: {ratio:.0%}.", ev,
                       fix="Fill the gaps listed; canonicals and breadcrumbs help answer engines cite the right page."))
    return out
