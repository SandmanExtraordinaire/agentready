"""Scan context: discovers which pages to test and caches parsed content."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetcher import Fetcher, Response, origin

PRODUCT_STRICT = re.compile(r"/(products?|p|dp|item|items|pd|sku)/[^/?#]+", re.I)
CATEGORY_PATTERNS = re.compile(r"/(collections?|category|categories|c|shop|catalog|department)/[^/?#]+", re.I)


@dataclass
class Pages:
    home: str
    category: str | None = None
    products: list[str] = field(default_factory=list)
    cart: str | None = None
    source: str = ""   # how products were found


@dataclass
class ScanContext:
    url: str
    fetcher: Fetcher
    pdp_samples: int = 4
    use_browser: bool = False
    manual_pages: list[str] = field(default_factory=list)
    label: str | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.origin = origin(self.url)
        self.robots: Response | None = None
        self.sitemap_urls: list[str] = []
        self.pages: Pages | None = None
        self._soups: dict[str, BeautifulSoup] = {}
        self.shared: dict = {}  # cross-check data (e.g. UCP profile, browser results)

    @property
    def display_name(self) -> str:
        return self.label or urlparse(self.origin).netloc

    # ---------- helpers ----------
    def abs(self, path: str) -> str:
        return urljoin(self.origin + "/", path)

    def get(self, url: str, **kw) -> Response:
        return self.fetcher.get(url, **kw)

    def soup(self, url: str) -> BeautifulSoup | None:
        if url not in self._soups:
            r = self.get(url)
            self._soups[url] = BeautifulSoup(r.text, "lxml") if r.ok and r.text else None
        return self._soups[url]

    def jsonld(self, url: str) -> list[dict]:
        s = self.soup(url)
        return extract_jsonld(s) if s else []

    # ---------- discovery ----------
    def discover(self) -> Pages:
        self.robots = self.get(self.abs("/robots.txt"), accept="text/plain,*/*")
        home_r = self.get(self.origin + "/")
        home = home_r.final_url if home_r.ok else self.origin + "/"
        pages = Pages(home=home)

        if self.manual_pages:
            for u in self.manual_pages:
                u = self.abs(u) if u.startswith("/") else u
                if CATEGORY_PATTERNS.search(u) and not pages.category:
                    pages.category = u
                else:
                    pages.products.append(u)
            pages.source = "provided by user"

        candidates: list[str] = []
        from_sitemap = self._sitemap_product_urls()  # always run: the sitemap check needs it
        if not pages.products and from_sitemap:
            candidates = from_sitemap
            pages.source = "sitemap"
        home_soup = self.soup(home)
        links = []
        if home_soup:
            for a in home_soup.find_all("a", href=True):
                u = urljoin(home, a["href"]).split("#")[0]
                if origin(u) == self.origin:
                    links.append(u)
        if not pages.products and not candidates:
            candidates = [u for u in dict.fromkeys(links) if PRODUCT_STRICT.search(urlparse(u).path)]
            if candidates:
                pages.source = "homepage links"
        if not pages.category:
            cats = [u for u in dict.fromkeys(links) if CATEGORY_PATTERNS.search(urlparse(u).path)]
            pages.category = cats[0] if cats else None
            if pages.category and not pages.products and not candidates:
                cs = self.soup(pages.category)
                if cs:
                    found = [urljoin(pages.category, a["href"]).split("#")[0]
                             for a in cs.find_all("a", href=True)]
                    candidates = [u for u in dict.fromkeys(found)
                                  if origin(u) == self.origin and PRODUCT_STRICT.search(urlparse(u).path)]
                    if candidates:
                        pages.source = "category page links"

        if not pages.products:
            pages.products = _spread(candidates, self.pdp_samples)
        if not pages.products:
            self.notes.append("No product pages found automatically. Re-run with --pages to name some.")

        for path in ("/cart", "/basket", "/bag", "/cart.php"):
            r = self.get(self.abs(path))
            if r.ok:
                pages.cart = r.final_url
                break
        self.pages = pages
        return pages

    def _sitemap_product_urls(self) -> list[str]:
        sitemap_refs = []
        if self.robots and self.robots.ok:
            sitemap_refs = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", self.robots.text)
        if not sitemap_refs:
            sitemap_refs = [self.abs("/sitemap.xml")]
        urls: list[str] = []
        queue = list(dict.fromkeys(sitemap_refs))[:3]
        seen = 0
        while queue and seen < 6:
            sm = queue.pop(0)
            seen += 1
            r = self.get(sm, accept="application/xml,text/xml,*/*")
            if not r.ok:
                continue
            self.sitemap_urls.append(sm)
            locs, children = _parse_sitemap(r.text)
            # Prefer child sitemaps that look like product sitemaps.
            children.sort(key=lambda u: 0 if "product" in u.lower() else 1)
            queue.extend(children[:3])
            urls.extend(u for u in locs if origin(u) == self.origin)
            if len([u for u in urls if PRODUCT_STRICT.search(urlparse(u).path)]) >= 50:
                break
        strict = [u for u in urls if PRODUCT_STRICT.search(urlparse(u).path)]
        return list(dict.fromkeys(strict))


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8", "ignore"))
    except ET.ParseError:
        return [], []
    tag = root.tag.split("}")[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.split("}")[-1] == "loc" and el.text]
    return ([], locs) if tag == "sitemapindex" else (locs, [])


def _spread(items: list[str], n: int) -> list[str]:
    """Pick n items spread across the list (templates vary by category)."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        out.extend(_flatten(data))
    return out


def _flatten(data) -> list[dict]:
    if isinstance(data, list):
        return [x for d in data for x in _flatten(d)]
    if isinstance(data, dict):
        items = [data]
        if "@graph" in data:
            items += _flatten(data["@graph"])
        return items
    return []


def types_of(node: dict) -> set[str]:
    t = node.get("@type", [])
    t = t if isinstance(t, list) else [t]
    return {str(x).split("/")[-1] for x in t}
