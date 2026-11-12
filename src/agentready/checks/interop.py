"""Layer: can another agent talk to this merchant's agent?"""
from __future__ import annotations

import json
import re

from ..models import CheckResult, Status
from . import check

WIDGETS = {
    "Intercom": r"widget\.intercom\.io|intercomcdn", "Zendesk": r"static\.zdassets\.com|zopim",
    "Drift": r"js\.driftt\.com", "Ada": r"static\.ada\.support", "LivePerson": r"liveperson\.net|lpsnmedia",
    "Salesforce Agentforce / Embedded Service": r"embeddedservice|salesforceliveagent|agentforce",
    "Gorgias": r"gorgias", "Tidio": r"code\.tidio\.co", "Freshchat": r"wchat\.freshchat|freshchat",
    "Kore.ai": r"kore\.ai", "Yellow.ai": r"yellow\.ai|yellowmessenger", "Haptik": r"haptik",
    "Verloop": r"verloop\.io", "Google Dialogflow": r"dialogflow", "Rufus-style assistant": r"shopping-assistant",
}


def _json(r):
    try:
        return json.loads(r.text) if r.ok else None
    except ValueError:
        return None


@check
def a2a_agent_card(ctx):
    res = CheckResult("a2a-agent-card", "interop", "A2A agent card", Status.FAIL, weight=2.0)
    for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        url = ctx.abs(path)
        data = _json(ctx.get(url, accept="application/json"))
        if isinstance(data, dict):
            fields = [k for k in ("name", "url", "skills", "capabilities") if data.get(k)]
            res.score = 1.0 if {"name", "url"} <= set(fields) else 0.5
            res.status = Status.PASS if res.score == 1 else Status.PARTIAL
            skills = [s.get("name") or s.get("id") for s in data.get("skills", []) if isinstance(s, dict)]
            res.summary = f"Agent card at {path}: {data.get('name', 'unnamed')}."
            if skills:
                res.evidence.append("Skills: " + ", ".join(map(str, skills[:10])))
            ctx.shared["agent_card"] = True
            return res
    ctx.shared["agent_card"] = False
    res.summary = "No A2A agent card published."
    res.fix = ("Publish /.well-known/agent-card.json describing the merchant agent's skills (product Q&A, "
               "order status, returns) so shoppers' agents can delegate to it.")
    return res


@check
def mcp_interface(ctx):
    res = CheckResult("mcp-interface", "interop", "MCP or A2A commerce interface", Status.FAIL, weight=2.0)
    transports = ctx.shared.get("ucp_transports") or []
    agentic = [t for t in transports if t in ("mcp", "a2a")]
    if agentic:
        res.status, res.score = Status.PASS, 1.0
        res.summary = f"UCP profile exposes {', '.join(agentic).upper()} transport(s)."
        return res
    for path in ("/.well-known/mcp.json", "/.well-known/mcp"):
        data = _json(ctx.get(ctx.abs(path), accept="application/json"))
        if isinstance(data, dict):
            res.status, res.score = Status.PARTIAL, 0.6
            res.summary = f"MCP discovery document found at {path} (not yet a ratified standard path)."
            return res
    res.summary = "No MCP or A2A interface discovered."
    res.fix = ("Expose catalog, cart and checkout as MCP tools or an A2A agent, ideally declared in the UCP "
               "profile so agents find them automatically.")
    return res


@check
def chat_widget(ctx):
    res = CheckResult("chat-widget", "interop", "On-site assistant (human-facing)", Status.INFO, weight=0)
    html = ctx.get(ctx.pages.home).text[:800000]
    found = [n for n, rx in WIDGETS.items() if re.search(rx, html, re.I)]
    res.data = {"widgets": found}
    res.summary = (f"Detected: {', '.join(found)}. A chat widget serves people; other agents can't call it "
                   "unless it is also exposed via MCP, A2A or UCP." if found
                   else "No on-site chat assistant detected.")
    return res
