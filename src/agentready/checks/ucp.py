"""Layer: Universal Commerce Protocol (UCP) discovery and capabilities.

UCP businesses publish a profile at /.well-known/ucp. The spec is versioned by
date and its shape has evolved (capabilities as a list in early versions, as a
name-keyed map later; services as objects or arrays). We accept both shapes and
validate structure, not every schema detail. Full JSON Schema validation against
the spec repo is on the roadmap (see docs/REQUIREMENTS.md).
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..models import CheckResult, Status, status_for
from . import check

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TRANSPORTS = ("rest", "mcp", "a2a", "embedded")
CAPABILITY_VALUE = {  # keyword in capability name -> score contribution
    "checkout": 0.45, "cart": 0.15, "catalog": 0.1, "order": 0.1,
    "identity": 0.1, "fulfillment": 0.05, "discount": 0.05,
}


def _entries(v) -> list[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return [v] if isinstance(v, dict) else []


def parse_profile(data: dict) -> dict:
    prof = data.get("ucp", data) if isinstance(data, dict) else {}
    services, endpoints, caps, specs = {}, [], {}, []
    for name, val in (prof.get("services") or {}).items():
        services[name] = _entries(val)
        for e in services[name]:
            specs.append((name, e.get("spec")))
            for t in TRANSPORTS:
                if isinstance(e.get(t), dict) and e[t].get("endpoint"):
                    endpoints.append({"service": name, "transport": t, "url": e[t]["endpoint"]})
            if e.get("transport") and e.get("endpoint"):
                endpoints.append({"service": name, "transport": e["transport"], "url": e["endpoint"]})
    raw_caps = prof.get("capabilities") or []
    if isinstance(raw_caps, dict):
        for name, val in raw_caps.items():
            caps[name] = _entries(val)
    else:
        for c in raw_caps:
            if isinstance(c, dict) and c.get("name"):
                caps.setdefault(c["name"], []).append(c)
    for name, entries in caps.items():
        for e in entries:
            specs.append((name, e.get("spec")))
    return {"version": prof.get("version"), "services": services, "capabilities": caps,
            "endpoints": endpoints, "specs": specs}


def namespace_ok(name: str, spec: str | None) -> bool:
    """dev.ucp.* specs must live on ucp.dev; com.acme.* on acme.com (spec governance rule)."""
    if not spec:
        return False
    host = urlparse(spec).netloc.lower()
    parts = name.split(".")
    if len(parts) < 2:
        return False
    authority = f"{parts[1]}.{parts[0]}"
    return host == authority or host.endswith("." + authority)


@check
def ucp_profile(ctx):
    res = CheckResult("ucp-profile", "ucp", "UCP discovery profile (/.well-known/ucp)", Status.FAIL, weight=3.0)
    url = ctx.abs("/.well-known/ucp")
    r = ctx.get(url, accept="application/json")
    ctx.shared["ucp"] = None
    if not r.ok:
        res.summary = f"No UCP profile (HTTP {r.status or r.error})."
        res.fix = ("Publish a UCP business profile at /.well-known/ucp declaring the shopping service, "
                   "transports (REST, MCP or A2A) and capabilities such as checkout. Commerce platforms "
                   "increasingly ship this; check the platform's UCP support first.")
        return res
    try:
        data = json.loads(r.text)
    except ValueError:
        res.summary = "/.well-known/ucp exists but is not valid JSON."
        res.score = 0.15
        res.fix = "Serve the profile as valid JSON with Content-Type application/json."
        return res
    p = parse_profile(data)
    ctx.shared["ucp"] = p
    bad_ns = [n for n, s in p["specs"] if not namespace_ok(n, s)]
    parts = {
        "valid JSON": 0.4,
        "dated version": 0.2 if DATE_RE.match(str(p["version"] or "")) else 0,
        "services declared": 0.2 if p["services"] else 0,
        "spec URLs match namespaces": 0.2 if p["specs"] and not bad_ns else 0,
    }
    res.score = sum(parts.values())
    res.status = status_for(res.score)
    res.summary = (f"UCP profile found, protocol version {p['version'] or 'missing'}, "
                   f"{len(p['services'])} service(s), {len(p['capabilities'])} capability declaration(s).")
    if "json" not in r.headers.get("content-type", ""):
        res.evidence.append(f"Content-Type is {r.headers.get('content-type')!r}, expected application/json")
    for n in bad_ns[:5]:
        res.evidence.append(f"{n}: spec URL missing or not on the namespace's own domain")
    res.data = {"version": p["version"], "services": list(p["services"]), "capabilities": list(p["capabilities"])}
    if res.status != Status.PASS:
        res.fix = "Fix the profile structure: dated version, declared services, and spec URLs on the namespace owner's domain."
    return res


@check
def ucp_capabilities(ctx):
    res = CheckResult("ucp-capabilities", "ucp", "UCP commerce capabilities", Status.SKIP, weight=3.0)
    p = ctx.shared.get("ucp")
    if not p:
        res.summary = "No UCP profile, so no capabilities to assess."
        res.status, res.score = Status.FAIL, 0.0
        return res
    names = list(p["capabilities"]) + list(p["services"])
    hit = {k: any(k in n.lower() for n in names) for k in CAPABILITY_VALUE}
    res.score = min(1.0, sum(v for k, v in CAPABILITY_VALUE.items() if hit[k]) / 0.85)
    res.status = status_for(res.score)
    ctx.shared["ucp_checkout"] = hit["checkout"]
    res.summary = ("Declares: " + ", ".join(k for k, v in hit.items() if v)) if any(hit.values()) \
        else "Profile declares no recognised commerce capabilities."
    res.evidence = [f"{n}" for n in p["capabilities"]][:12]
    if not hit["checkout"]:
        res.fix = "Declare and implement dev.ucp.shopping.checkout; without it agents can browse but not buy."
    return res


@check
def ucp_endpoints(ctx):
    res = CheckResult("ucp-endpoints", "ucp", "UCP endpoints respond", Status.SKIP, weight=2.0)
    p = ctx.shared.get("ucp")
    if not p or not p["endpoints"]:
        res.summary = "No UCP endpoints declared." if p else "No UCP profile."
        if p:
            res.status, res.score = Status.FAIL, 0.0
        return res
    ok = 0
    eps = p["endpoints"][:8]
    for e in eps:
        r = ctx.get(e["url"], accept="application/json", label="ucp-probe")
        alive = r.status is not None and r.status < 500
        ok += alive
        res.evidence.append(f"{e['transport']} {e['url']} → {r.status or r.error}")
    res.score = ok / len(eps)
    res.status = status_for(res.score)
    ctx.shared["ucp_endpoints_ok"] = res.score >= 0.85
    transports = sorted({e["transport"] for e in p["endpoints"]})
    ctx.shared["ucp_transports"] = transports
    res.summary = f"{ok} of {len(eps)} declared endpoints answered (transports: {', '.join(transports)})."
    res.evidence.append("Probe is a plain GET for liveness only; no sessions are created.")
    if ok < len(eps):
        res.fix = "Every endpoint in the profile must be reachable; agents abandon a merchant after a failed call."
    return res
