"""A fake store served on localhost, so every check can be tested offline."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from werkzeug.wrappers import Response

FIXTURES = Path(__file__).parent / "fixtures"

PRODUCT_LD = {
    "@context": "https://schema.org", "@type": "Product", "name": "Trail Runner 2",
    "image": "https://example.com/img.jpg", "description": "Lightweight trail shoe.",
    "sku": "TR2-42", "gtin13": "4006381333931", "brand": {"@type": "Brand", "name": "Northpeak"},
    "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.6, "reviewCount": 212},
    "offers": {"@type": "Offer", "price": "129.00", "priceCurrency": "USD",
               "availability": "https://schema.org/InStock",
               "hasMerchantReturnPolicy": {"@type": "MerchantReturnPolicy", "merchantReturnDays": 30},
               "shippingDetails": {"@type": "OfferShippingDetails"}},
}
ORG_LD = {"@context": "https://schema.org", "@type": "Organization", "name": "Northpeak",
          "url": "https://example.com", "logo": "https://example.com/logo.png",
          "sameAs": ["https://instagram.com/northpeak"]}


def page(title: str, body: str, ld: dict | None = None) -> str:
    ld_tag = f'<script type="application/ld+json">{json.dumps(ld)}</script>' if ld else ""
    return (f"<html><head><title>{title}</title><meta name='description' content='{title}'>"
            f"<link rel='canonical' href='/'><meta property='og:title' content='{title}'>"
            f"<meta property='og:image' content='/i.jpg'>{ld_tag}</head><body>{body}"
            + "<p>Filler copy about trail running and outdoor gear. </p>" * 40 + "</body></html>")


def mcp_handler(request):
    msg = request.get_json(silent=True) or {}
    if msg.get("method") == "initialize":
        body = {"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "northpeak-commerce", "version": "1"}}}
        return Response(json.dumps(body), headers={"Mcp-Session-Id": "abc"}, content_type="application/json")
    if msg.get("method") == "tools/list":
        body = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
            {"name": "search_catalog"}, {"name": "create_checkout"}]}}
        return Response(json.dumps(body), content_type="application/json")
    return Response("", status=202)


@pytest.fixture
def good_store(httpserver):
    base = httpserver.url_for("").rstrip("/")
    profile = json.loads((FIXTURES / "ucp_profile_valid.json").read_text())
    for entries in profile["ucp"]["services"].values():
        for e in entries:
            if "endpoint" in e:
                e["endpoint"] = {"rest": f"{base}/ucp/v1", "mcp": f"{base}/ucp/mcp",
                                 "a2a": f"{base}/.well-known/agent-card.json"}[e["transport"]]
    s = httpserver
    s.expect_request("/robots.txt").respond_with_data(
        f"User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")
    s.expect_request("/sitemap.xml").respond_with_data(
        f"<?xml version='1.0'?><urlset><url><loc>{base}/products/trail-runner-2</loc></url>"
        f"<url><loc>{base}/collections/shoes</loc></url></urlset>", content_type="application/xml")
    s.expect_request("/").respond_with_data(
        page("Northpeak", "<a href='/products/trail-runner-2'>Trail Runner 2</a>", ORG_LD), content_type="text/html")
    s.expect_request("/collections/shoes").respond_with_data(
        page("Shoes", "<a href='/products/trail-runner-2'>Trail Runner 2</a>",
             {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": []}),
        content_type="text/html")
    s.expect_request("/products/trail-runner-2").respond_with_data(
        page("Trail Runner 2", "<h1>Trail Runner 2</h1><p>$129.00</p><button>Add to cart</button>", PRODUCT_LD),
        content_type="text/html")
    s.expect_request("/.well-known/ucp").respond_with_json(profile)
    s.expect_request("/ucp/v1").respond_with_data("", status=404)
    s.expect_request("/ucp/mcp", method="POST").respond_with_handler(mcp_handler)
    s.expect_request("/.well-known/agent-card.json").respond_with_json({
        "name": "Northpeak shopping agent", "url": f"{base}/a2a",
        "skills": [{"id": "find", "name": "Find products"}, {"id": "order", "name": "Track orders"}]})
    s.expect_request("/llms.txt").respond_with_data("# Northpeak\n> Outdoor gear store. Key pages below.\n",
                                                    content_type="text/plain")
    s.expect_request("/cart").respond_with_data(page("Cart", "<h1>Your cart</h1>"), content_type="text/html")
    return base


def walled_handler(request):
    ua = request.headers.get("User-Agent", "")
    if any(t in ua for t in ("ChatGPT-User", "OAI-SearchBot", "Claude-User", "PerplexityBot", "Googlebot")):
        return Response("<html><title>Just a moment...</title>challenge-platform</html>", status=403,
                        content_type="text/html")
    # Client-side rendered shell: no content, no markup
    return Response("<html><head><title>Shop</title></head><body><div id='root'></div>"
                    "<script src='/app.js'></script></body></html>", content_type="text/html")


@pytest.fixture
def walled_store(httpserver):
    base = httpserver.url_for("").rstrip("/")
    s = httpserver
    s.expect_request("/robots.txt").respond_with_data(
        "User-agent: OAI-SearchBot\nDisallow: /\nUser-agent: ChatGPT-User\nDisallow: /\n"
        "User-agent: Claude-User\nDisallow: /\nUser-agent: PerplexityBot\nDisallow: /\n"
        "User-agent: Claude-SearchBot\nDisallow: /\nUser-agent: Perplexity-User\nDisallow: /\n"
        "User-agent: Bingbot\nDisallow: /\n")
    for path in ("/", "/products/thing", "/cart"):
        s.expect_request(path).respond_with_handler(walled_handler)
    return base
