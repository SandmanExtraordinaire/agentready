"""Layer 1 — can AI agents get in at all?"""
from __future__ import annotations

from protego import Protego

from ..agents import AGENTS, BROWSER_UA, PROBE_TOKENS
from ..models import Finding, Status
from . import ScanContext, check

BLOCK_CODES = {401, 403, 406, 429, 451, 503}


@check("access")
def robots_rules(ctx: ScanContext) -> list[Finding]:
    r = ctx.discovery.robots
    out: list[Finding] = []
    if r is None or r.status is None:
        out.append(Finding("robots_file", "access", "robots.txt is reachable", Status.FAIL,
                           "robots.txt could not be fetched.", [r.error if r else "no response"],
                           fix="Serve /robots.txt with a 200 or 404; network errors make crawlers back off."))
        return out
    if r.status == 404:
        out.append(Finding("robots_file", "access", "robots.txt is reachable", Status.PASS,
                           "No robots.txt (404) — every crawler is allowed by default.",
                           [f"{r.url} → 404"],
                           fix="Optional: publish a robots.txt that states your AI-agent policy explicitly."))
        ctx.shared["robots"] = Protego.parse("")
    elif r.status >= 500 or (r.status in BLOCK_CODES):
        out.append(Finding("robots_file", "access", "robots.txt is reachable", Status.PARTIAL,
                           f"robots.txt returned {r.status}. Several crawlers treat this as 'disallow everything'.",
                           [f"{r.url} → {r.status}"],
                           fix="Make sure /robots.txt returns 200 to bots as well as browsers."))
        ctx.shared["robots"] = Protego.parse("User-agent: *\nDisallow: /")
    else:
        out.append(Finding("robots_file", "access", "robots.txt is reachable", Status.PASS,
                           "robots.txt is published.", [f"{r.url} → {r.status}"]))
        ctx.shared["robots"] = Protego.parse(r.text)

    rp: Protego = ctx.shared["robots"]
    product = next((p.url for p in ctx.pages("product")), None)
    targets = {"home": ctx.base + "/", "product": product, "ucp": ctx.base + "/.well-known/ucp"}
    rows, blocked_important, blocked_training = [], [], []
    for a in AGENTS:
        row = {"agent": a.token, "vendor": a.vendor, "role": a.role}
        for name, url in targets.items():
            row[name] = None if url is None else rp.can_fetch(url, a.token)
        rows.append(row)
        denied = row["home"] is False or row["product"] is False
        if denied and a.role in ("search", "user"):
            blocked_important.append(a.token)
        elif denied:
            blocked_training.append(a.token)

    important = [a for a in AGENTS if a.role in ("search", "user")]
    if not blocked_important:
        status, summary = Status.PASS, "Every AI search and assistant agent is allowed to read home and product pages."
    elif len(blocked_important) < len(important) / 2:
        status, summary = Status.PARTIAL, f"Some AI search/assistant agents are disallowed: {', '.join(blocked_important)}."
    else:
        status, summary = Status.FAIL, f"Most AI search/assistant agents are disallowed: {', '.join(blocked_important)}."
    ev = [f"Training crawlers disallowed (a legitimate choice, not scored): {', '.join(blocked_training)}"] if blocked_training else []
    out.append(Finding(
        "robots_ai_agents", "access", "robots.txt lets AI agents in", status, summary, ev,
        fix="Allow search and user-initiated agents (OAI-SearchBot, ChatGPT-User, Claude-User, "
            "PerplexityBot, Googlebot, Bingbot) on product and category paths. You can still block training crawlers.",
        data={"rows": rows},
    ))
    return out


@check("access")
def bot_wall(ctx: ScanContext) -> list[Finding]:
    """Fetch the same page as a browser and as each agent; compare."""
    fx = ctx.fetcher
    urls = [ctx.base + "/"] + [p.url for p in ctx.pages("product")[:1]]
    rows, blocked = [], set()
    baseline_blocked = False
    for url in urls:
        base = fx.get(url, ua=BROWSER_UA, accept="text/html")
        if not base.ok or base.looks_like_challenge():
            baseline_blocked = True
        for a in AGENTS:
            if a.token not in PROBE_TOKENS or not a.ua:
                continue
            r = fx.get(url, ua=a.ua, accept="text/html")
            reason = ""
            if r.status is None:
                reason = "no response"
            elif r.status in BLOCK_CODES:
                reason = f"HTTP {r.status}"
            elif r.looks_like_challenge():
                reason = "challenge page"
            elif base.ok and len(base.text) > 20_000 and len(r.text) < 0.25 * len(base.text):
                reason = f"thin page ({len(r.text):,} vs {len(base.text):,} bytes)"
            if reason:
                blocked.add(a.token)
            rows.append({"url": url, "agent": a.token, "status": r.status,
                         "bytes": len(r.text), "browser_status": base.status, "blocked": reason})

    probed = [t for t in PROBE_TOKENS]
    if baseline_blocked:
        status = Status.PARTIAL
        summary = "The site challenged even a normal browser request, so agent results are inconclusive."
    elif not blocked:
        status, summary = Status.PASS, "Agent user-agents received the same pages as a browser."
    elif len(blocked) < len(probed) / 2:
        status, summary = Status.PARTIAL, f"Bot protection treated some agents differently: {', '.join(sorted(blocked))}."
    else:
        status, summary = Status.FAIL, f"Bot protection blocks most AI agents: {', '.join(sorted(blocked))}."
    return [Finding(
        "bot_wall", "access", "Bot protection lets AI agents through", status, summary,
        [f"{r['agent']} on {r['url']}: {r['status']} {r['blocked'] or 'ok'}" for r in rows],
        fix="In your CDN/WAF (Cloudflare, Akamai, Imperva…), allow verified AI search and user agents, "
            "or adopt Web Bot Auth so signed agents can be told apart from scrapers.",
        confidence="inferred",
        data={"rows": rows, "note": "Probed with the agents' user-agent strings from our IP. Real agents may be "
                                    "verified by IP or signature, so a block here strongly suggests — but does not "
                                    "prove — the real agent is blocked."},
    )]
