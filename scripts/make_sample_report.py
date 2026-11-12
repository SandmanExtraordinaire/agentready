#!/usr/bin/env python3
"""Rebuild docs/sample-report.html from the offline test stores (synthetic data only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pytest_httpserver import HTTPServer  # noqa: E402

from agentready.report import render_html  # noqa: E402
from agentready.scanner import scan  # noqa: E402
from tests import conftest  # noqa: E402

servers = []
try:
    g, w = HTTPServer(port=0), HTTPServer(port=0)
    for s in (g, w):
        s.start()
        servers.append(s)
    good, walled = conftest.good_store.__wrapped__(g), conftest.walled_store.__wrapped__(w)
    quiet = dict(use_browser=False, delay=0, log=lambda *a: None)
    client = scan(walled, product_urls=[walled + "/products/thing"], **quiet)
    rival = scan(good, **quiet)
    client.domain, rival.domain = "client-store.example", "rival-outdoors.example"
    html = render_html([client, rival])
    html = html.replace(walled, "https://client-store.example").replace(good, "https://rival-outdoors.example")
    (ROOT / "docs" / "sample-report.html").write_text(html, encoding="utf-8")
    print("wrote docs/sample-report.html")
finally:
    for s in servers:
        s.stop()
