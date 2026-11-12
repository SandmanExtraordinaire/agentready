"""agentready scan client.com --vs competitor.com --vs other.com"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .report import write
from .scanner import scan


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentready", description="Agentic commerce readiness scanner")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="scan a store (and optional competitors) and write a report")
    s.add_argument("target", help="domain or URL of the store, e.g. example.com")
    s.add_argument("--vs", action="append", default=[], metavar="DOMAIN",
                   help="competitor to compare against (repeatable)")
    s.add_argument("--product-url", action="append", default=[], metavar="URL",
                   help="product page to scan on the main store (repeatable); skips auto-discovery")
    s.add_argument("--category-url", action="append", default=[], metavar="URL")
    s.add_argument("--max-products", type=int, default=4)
    s.add_argument("--no-browser", action="store_true", help="skip headless-browser checks")
    s.add_argument("--delay", type=float, default=0.6, help="seconds between requests to one host")
    s.add_argument("--out", type=Path, default=Path("reports"), help="output folder (git-ignored)")
    s.add_argument("--name", help="report file name without extension")
    s.add_argument("--insecure", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.cmd == "scan":
        results = []
        for i, target in enumerate([args.target, *args.vs]):
            results.append(scan(
                target, max_products=args.max_products,
                product_urls=args.product_url if i == 0 else None,
                category_urls=args.category_url if i == 0 else None,
                use_browser=not args.no_browser, delay=args.delay, verify_tls=not args.insecure,
            ))
        html, js = write(results, args.out, args.name)
        print(f"\nReport: {html}\nData:   {js}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
