"""Layer 2 — does the store speak an agentic commerce protocol?

UCP is verifiable from outside: the business profile is public at
/.well-known/ucp. ACP is not: merchants integrate privately with OpenAI /
Stripe, so we only report signals and label them as inferred."""
from __future__ import annotations

import json
import re
from typing import Iterator

from ..agents import BROWSER_UA
from ..mcp import probe_mcp
from ..models import Finding, Status
from ..ucp_schema import latest_version, validate_profile
from . import ScanContext, check

CHECKOUT_CAPS = ("dev.ucp.shopping.checkout", "dev.ucp.shopping.cart")


def iter_services(profile: dict) -> Iterator[tuple[str, str, str]]:
    """Yield (service, transport, endpoint) across UCP profile shapes."""
    services = (profile.get("ucp") or {}).get("services") or {}
    for name, spec in services.items():
        if isinstance(spec, list):                      # 2026-01-23 onwards
            for entry in spec:
                if isinstance(entry, dict):
                    yield name, str(entry.get("transport", "?")), str(entry.get("endpoint", ""))
        elif isinstance(spec, dict):                    # 2026-01-11
            for transport in ("rest", "mcp", "a2a", "embedded"):
                if isinstance(spec.get(transport), dict):
                    yield name, transport, str(spec[transport].get("endpoint", ""))


def capability_names(profile: dict) -> list[str]:
    caps = (profile.get("ucp") or {}).get("capabilities") or {}
    if isinstance(caps, dict):
        return sorted(caps)
    return sorted(c.get("name", "?") for c in caps if isinstance(c, dict))


@check("protocols")
def ucp(ctx: ScanContext) -> list[Finding]:
    fx = ctx.fetcher
    url = ctx.base + "/.well-known/ucp"
    r = fx.get(url, accept="application/json")
    out: list[Finding] = []
    fix_publish = ("Publish a UCP business profile at /.well-known/ucp declaring your services, "
                   "capabilities (checkout, cart, catalog) and payment handlers. Shopify, commercetools "
                   "and others can generate this; see ucp.dev.")
    profile = None
    if r.ok:
        try:
            profile = json.loads(r.text)
        except json.JSONDecodeError:
            pass
    if profile is None or not isinstance(profile, dict):
        why = f"{url} → {r.status or r.error}"
        if r.ok:
            why += " (not JSON)"
        out.append(Finding("ucp_profile", "protocols", "UCP profile is published and valid", Status.FAIL,
                           "No UCP business profile found, so agents cannot discover what the store can do.",
                           [why], fix=fix_publish))
        for fid, title in [("ucp_checkout", "UCP declares checkout or cart"),
                           ("ucp_endpoints", "UCP endpoints respond")]:
            out.append(Finding(fid, "protocols", title, Status.FAIL, "Not applicable without a UCP profile.",
                               fix=fix_publish))
        return out

    ctx.shared["ucp_profile"] = profile
    version_used, errors = validate_profile(profile)
    declared = str((profile.get("ucp") or {}).get("version", "?"))
    caps = capability_names(profile)
    services = list(iter_services(profile))
    ev = [f"{url} → {r.status}", f"Declared version {declared}; validated against UCP {version_used} schema",
          f"Capabilities: {', '.join(caps) or 'none'}",
          *[f"Service {s} via {t}: {e or '(in-page)'}" for s, t, e in services]]
    out.append(Finding(
        "ucp_profile", "protocols", "UCP profile is published and valid",
        Status.PASS if not errors else Status.PARTIAL,
        "A valid UCP business profile is published." if not errors
        else f"A UCP profile is published but has {len(errors)} schema error(s); strict agents may reject it.",
        ev + [f"Schema error: {e}" for e in errors],
        fix="" if not errors else "Fix the schema errors listed; validate with the official schemas before deploying.",
        data={"declared_version": declared, "schema_version": version_used, "capabilities": caps,
              "services": [{"service": s, "transport": t, "endpoint": e} for s, t, e in services],
              "errors": errors},
    ))

    has_txn = [c for c in caps if c in CHECKOUT_CAPS]
    out.append(Finding(
        "ucp_checkout", "protocols", "UCP declares checkout or cart",
        Status.PASS if has_txn else Status.FAIL,
        f"Agents can transact through: {', '.join(has_txn)}." if has_txn
        else "The profile does not declare checkout or cart, so agents can browse but not buy.",
        [f"Capabilities: {', '.join(caps) or 'none'}"],
        fix="" if has_txn else "Add dev.ucp.shopping.checkout (and ideally cart) to the profile.",
    ))

    latest = latest_version()
    current = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", declared)) and declared >= latest
    out.append(Finding(
        "ucp_version", "protocols", "UCP version is current",
        Status.PASS if current else Status.PARTIAL,
        f"Profile declares {declared}; latest release we know is {latest}.",
        fix="" if current else f"Plan an upgrade to UCP {latest} (or advertise it via supported_versions).",
    ))

    # Endpoint liveness. Read-only: GET for REST/A2A, MCP initialize handshake for MCP.
    rows, live, total = [], 0, 0
    for svc, transport, endpoint in services:
        if not endpoint.startswith("http"):
            continue
        total += 1
        if transport == "mcp":
            m = probe_mcp(fx, endpoint)
            ok = m.reachable
            rows.append(f"{transport} {endpoint}: {m.detail}")
            ctx.shared.setdefault("mcp_probes", []).append(m)
        else:
            resp = fx.get(endpoint, accept="application/json")
            ok = resp.status is not None and resp.status < 500
            note = " (404 at a REST base path is normal)" if resp.status == 404 and transport == "rest" else ""
            rows.append(f"{transport} {endpoint}: {resp.status or resp.error}{note}")
        live += ok
    if total == 0:
        status, summary = Status.PARTIAL, "The profile lists no HTTP endpoints to check."
    elif live == total:
        status, summary = Status.PASS, f"All {total} declared endpoints respond."
    elif live:
        status, summary = Status.PARTIAL, f"{live} of {total} declared endpoints respond."
    else:
        status, summary = Status.FAIL, "None of the declared endpoints respond."
    out.append(Finding("ucp_endpoints", "protocols", "UCP endpoints respond", status, summary, rows,
                       fix="" if status == Status.PASS else "Make every endpoint in the profile reachable from the public internet."))
    return out


PLATFORMS = {
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme", r"myshopify\.com"],
    "Salesforce Commerce Cloud": [r"demandware\.", r"/on/demandware\.static/"],
    "Adobe Commerce (Magento)": [r"Magento_", r"mage/cookies", r"static/version\d+/frontend"],
    "BigCommerce": [r"cdn\d*\.bigcommerce\.com", r"stencil-utils"],
    "WooCommerce": [r"woocommerce", r"wc-ajax"],
    "commercetools": [r"commercetools"],
    "Wix": [r"static\.wixstatic\.com"],
}
# Platforms with announced ChatGPT Instant Checkout / ACP rollouts.
ACP_PLATFORMS = {"Shopify"}


@check("protocols")
def acp_signals(ctx: ScanContext) -> list[Finding]:
    html = " ".join(p.html[:400_000] for p in ctx.pages())
    platforms = [name for name, pats in PLATFORMS.items() if any(re.search(p, html, re.I) for p in pats)]
    ctx.shared["platforms"] = platforms
    stripe = bool(re.search(r"js\.stripe\.com", html))
    if ctx.discovery.base_url.endswith("etsy.com"):
        platforms.append("Etsy")
    signals = []
    if any(p in ACP_PLATFORMS or p == "Etsy" for p in platforms):
        signals.append(f"Runs on {', '.join(platforms)}, a platform with an announced ChatGPT Instant Checkout (ACP) rollout")
    if stripe:
        signals.append("Uses Stripe.js; Stripe is ACP's reference payment provider")
    profile = ctx.shared.get("ucp_profile")
    if profile and re.search(r"agentic.?commerce|\bacp\b", json.dumps(profile), re.I):
        signals.append("UCP profile references ACP")
    return [Finding(
        "acp_signals", "protocols", "ACP (ChatGPT checkout) signals", Status.INFO,
        f"{len(signals)} signal(s) found. ACP integrations are private, so this cannot be verified from outside."
        if signals else "No ACP signals found. ACP integrations are private, so absence is not proof.",
        signals + ([f"Platform(s) detected: {', '.join(platforms)}"] if platforms else []),
        fix="Confirm with the client whether they are enrolled in ChatGPT Instant Checkout / ACP.",
        confidence="inferred", data={"platforms": platforms, "stripe": stripe},
    )]
