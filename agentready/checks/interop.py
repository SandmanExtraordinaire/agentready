"""Layer 3 — is there an agent on the store's side that my agent can talk to?"""
from __future__ import annotations

import json
import re

from ..mcp import probe_mcp
from ..models import Finding, Status
from . import ScanContext, check
from .protocols import iter_services

CARD_PATHS = ["/.well-known/agent-card.json", "/.well-known/agent.json"]   # current, legacy A2A
MCP_HINT_PATHS = ["/.well-known/mcp.json"]                                   # draft convention

CHAT_VENDORS = {
    "Intercom": r"widget\.intercom\.io|intercomcdn", "Zendesk": r"static\.zdassets\.com|zopim",
    "Drift": r"js\.driftt\.com", "LivePerson": r"lpsnmedia\.net|liveperson",
    "Salesforce Embedded Service": r"embeddedservice|esw\.min\.js|salesforce-scrt",
    "Gorgias": r"gorgias\.chat|gorgias", "Tidio": r"code\.tidio\.co",
    "Ada": r"static\.ada\.support", "Freshchat": r"wchat\.freshchat\.com|freshworks",
    "Yellow.ai": r"yellow\.ai|ymchat", "Haptik": r"haptik", "Kore.ai": r"kore\.ai",
    "Rep AI": r"hellorep\.ai", "Shopify Inbox": r"shopify-chat|inbox\.shopify",
}


@check("interop")
def a2a_card(ctx: ScanContext) -> list[Finding]:
    fx = ctx.fetcher
    candidates = [ctx.base + p for p in CARD_PATHS]
    profile = ctx.shared.get("ucp_profile") or {}
    candidates += [e for _, t, e in iter_services(profile) if t == "a2a" and e.startswith("http")]
    tried = []
    for url in dict.fromkeys(candidates):
        r = fx.get(url, accept="application/json")
        tried.append(f"{url} → {r.status or r.error}")
        if not r.ok:
            continue
        try:
            card = json.loads(r.text)
        except json.JSONDecodeError:
            continue
        if not isinstance(card, dict) or "name" not in card:
            continue
        skills = [s.get("name") or s.get("id", "?") for s in card.get("skills", []) if isinstance(s, dict)]
        ctx.shared["agent_card"] = card
        complete = bool(skills) and bool(card.get("url") or card.get("supportedInterfaces"))
        return [Finding(
            "a2a_card", "interop", "Store publishes an A2A agent card",
            Status.PASS if complete else Status.PARTIAL,
            f"Agent '{card.get('name')}' advertises {len(skills)} skill(s)." if skills
            else f"Agent card '{card.get('name')}' found but it lists no skills.",
            tried + [f"Skills: {', '.join(skills[:12])}"] if skills else tried,
            fix="" if complete else "List the agent's skills and service URL in the card so other agents know what to ask it.",
            data={"card_url": url, "skills": skills},
        )]
    return [Finding("a2a_card", "interop", "Store publishes an A2A agent card", Status.FAIL,
                    "No agent card found, so a shopper's agent has no store agent to negotiate with.", tried,
                    fix="If the store has (or plans) a shopping assistant, expose it via A2A with an agent card at "
                        "/.well-known/agent-card.json.")]


@check("interop")
def mcp_server(ctx: ScanContext) -> list[Finding]:
    probes = list(ctx.shared.get("mcp_probes", []))
    seen = {p.endpoint for p in probes}
    hints = []
    for path in MCP_HINT_PATHS:
        r = ctx.fetcher.get(ctx.base + path, accept="application/json")
        hints.append(f"{ctx.base + path} → {r.status or r.error}")
        if r.ok:
            try:
                doc = json.loads(r.text)
                for key in ("url", "endpoint"):
                    if isinstance(doc.get(key), str) and doc[key] not in seen:
                        probes.append(probe_mcp(ctx.fetcher, doc[key]))
                        seen.add(doc[key])
            except (json.JSONDecodeError, AttributeError):
                pass
    verified = [p for p in probes if p.is_mcp]
    ev = hints + [f"{p.endpoint}: {p.detail}" + (f" — tools: {', '.join(p.tools[:10])}" if p.tools else "")
                  for p in probes]
    if verified:
        return [Finding("mcp_server", "interop", "Store exposes an MCP server", Status.PASS,
                        f"Verified MCP server(s): {', '.join(p.server_name or p.endpoint for p in verified)}.", ev,
                        data={"tools": sorted({t for p in verified for t in p.tools})})]
    return [Finding("mcp_server", "interop", "Store exposes an MCP server", Status.FAIL,
                    "No MCP server found via the UCP profile or well-known paths.", ev,
                    fix="Expose catalog search, cart and checkout as MCP tools and declare the endpoint in the "
                        "UCP profile (transport: mcp).")]


@check("interop")
def chat_assistant(ctx: ScanContext) -> list[Finding]:
    html = " ".join(p.html[:400_000] for p in ctx.pages())
    found = [name for name, pat in CHAT_VENDORS.items() if re.search(pat, html, re.I)]
    return [Finding(
        "chat_assistant", "interop", "On-site chat or shopping assistant", Status.INFO,
        f"Human-facing assistant detected: {', '.join(found)}. Useful foundation, but other agents can't call it."
        if found else "No on-site chat or assistant widget detected.",
        fix="An existing assistant is the fastest path to an A2A/MCP agent: expose its skills through a protocol."
        if found else "", confidence="inferred", data={"vendors": found},
    )]
