"""Find the pages worth scanning from just a domain: home, a category page,
a handful of product pages, and the cart. Uses robots.txt sitemaps first,
then homepage links. Manual URLs always win."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .agents import BROWSER_UA
from .http import Fetcher, Response
from .models import Page

PRODUCT_PATTERNS = [
    r"/products?/[^/]+", r"/p/[^/]+", r"/dp/[A-Z0-9]{8,}", r"/item/[^/]+",
    r"/ip/[^/]+", r"-p-\d+", r"/pd/[^/]+", r"/buy/[^/]+", r"\.html?$",
]
CATEGORY_PATTERNS = [
    r"/collections?/[^/]+/?$", r"/c/[^/]+", r"/category/[^/]+", r"/categories/[^/]+",
    r"/shop/[^/]+/?$", r"/department/[^/]+", r"/browse/[^/]+",
]
CART_PATHS = ["/cart", "/basket", "/bag", "/checkout/cart"]
NOT_PAGES = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|css|js|ico|xml|json|zip)(\?|$)", re.I)


def normalise_base(target: str) -> str:
    if "://" not in target:
        target = "https://" + target
    p = urlparse(target)
    return f"{p.scheme}://{p.netloc}"


def classify(url: str) -> str:
    path = urlparse(url).path.lower()
    if NOT_PAGES.search(path):
        return "asset"
    if "/collections/" in path and "/products/" in path:
        return "product"
    if any(re.search(p, path, re.I) for p in CATEGORY_PATTERNS):
        return "category"
    if any(re.search(p, path, re.I) for p in PRODUCT_PATTERNS[:-1]):
        return "product"
    return "other"


def spread(items: list[str], n: int) -> list[str]:
    """Pick n items spaced across the list (different templates/sections)."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


@dataclass
class Discovery:
    base_url: str
    robots: Response | None = None
    sitemaps: list[str] = field(default_factory=list)
    sitemap_url_count: int = 0
    pages: list[Page] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _locs(xml: str) -> list[str]:
    return [u.strip() for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml, re.I)]


def _read_sitemaps(fx: Fetcher, starts: list[str], limit: int = 4000) -> tuple[list[str], list[str]]:
    seen_maps: list[str] = []
    urls: list[str] = []
    queue = list(starts)
    while queue and len(seen_maps) < 8 and len(urls) < limit:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        r = fx.get(sm)
        if not r.ok or "<" not in r.text[:200]:
            continue
        seen_maps.append(sm)
        locs = _locs(r.text)
        if "<sitemapindex" in r.text[:2000].lower():
            # Product sitemaps first: they are what agents care about most.
            locs.sort(key=lambda u: (0 if "product" in u.lower() else 1 if "collection" in u.lower() or "categor" in u.lower() else 2))
            queue[:0] = locs[:4]
        else:
            urls.extend(locs)
    return seen_maps, urls[:limit]


def _links(html: str, base: str, host: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"]).split("#")[0]
        if urlparse(u).netloc == host and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _page(fx: Fetcher, url: str, kind: str) -> Page:
    r = fx.get(url, ua=BROWSER_UA, accept="text/html,application/xhtml+xml")
    return Page(url=url, kind=kind, status=r.status, html=r.text if r.ok else "",
                headers=r.headers, final_url=r.final_url, error=r.error)


def discover(fx: Fetcher, target: str, max_products: int = 4,
             product_urls: list[str] | None = None,
             category_urls: list[str] | None = None) -> Discovery:
    base = normalise_base(target)
    host = urlparse(base).netloc
    d = Discovery(base_url=base)

    d.robots = fx.get(base + "/robots.txt")
    robot_maps = []
    if d.robots.ok:
        robot_maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", d.robots.text)
    starts = robot_maps or [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    d.sitemaps, sm_urls = _read_sitemaps(fx, starts)
    d.sitemap_url_count = len(sm_urls)

    home = _page(fx, base + "/", "home")
    d.pages.append(home)

    products = list(product_urls or [])
    categories = list(category_urls or [])
    if not products or not categories:
        pool = [u for u in sm_urls if urlparse(u).netloc.endswith(host.removeprefix("www."))]
        if home.html:
            pool += _links(home.html, home.final_url or base, host)
        if not products:
            products = spread([u for u in dict.fromkeys(pool) if classify(u) == "product"], max_products)
        if not categories:
            categories = [u for u in dict.fromkeys(pool) if classify(u) == "category"][:1]

    # Last resort: follow a category page's links to find products.
    if not products and categories:
        cat = _page(fx, categories[0], "category")
        if cat.html:
            products = spread([u for u in _links(cat.html, cat.final_url, host) if classify(u) == "product"], max_products)

    for u in categories[:1]:
        if not any(p.url == u for p in d.pages):
            d.pages.append(_page(fx, u, "category"))
    for u in products[:max_products]:
        d.pages.append(_page(fx, u, "product"))

    if not products:
        d.notes.append("No product pages found automatically. Re-run with --product-url to scan specific products.")
    if not categories:
        d.notes.append("No category page found automatically. Use --category-url to add one.")
    return d
