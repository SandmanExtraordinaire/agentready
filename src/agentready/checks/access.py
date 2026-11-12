"""Layer: can AI agents reach the site at all?"""
from __future__ import annotations

import re
from urllib import robotparser
from urllib.parse import urlparse

from ..fetcher import AGENTS, BROWSER_UA
from ..models import CheckResult, Status, status_for
from . import check

PURPOSE_WEIGHT = {"user": 2.0, "search": 1.0, "training": 0.0}
CHALLENGE_MARKERS = re.compile(
    r"just a moment\.\.\.|attention required|cf-chl-|captcha|px-captcha|_incapsula_|"
    r"access denied|request unsuccessful|are you a robot|bot detection", re.I)


def _robots(ctx) -> robotparser.RobotFileParser | None:
    rp = robotparser.RobotFileParser()
    r = ctx.robots
    if r is None or r.status is None:
        return None
    if r.status in (401, 403):
        rp.disallow_all = True
    elif r.ok:
        rp.parse(r.text.splitlines())
    else:
        rp.allow_all = True
    return rp


@check
def robots_ai_agents(ctx):
    rp = _robots(ctx)
    res = CheckResult("robots-ai-agents", "access", "robots.txt rules for AI agents",
                      Status.SKIP, weight=3.0)
    if rp is None:
        res.summary = "robots.txt could not be fetched."
        return res
    test_urls = [ctx.pages.home] + ctx.pages.products[:1]
    rows, num, den, blocked_training = [], 0.0, 0.0, []
    for a in AGENTS:
        allowed = all(rp.can_fetch(a.name, u) for u in test_urls)
        rows.append({"agent": a.name, "owner": a.owner, "purpose": a.purpose, "allowed": allowed})
        w = PURPOSE_WEIGHT[a.purpose]
        num += w * allowed
        den += w
        if not allowed and a.purpose == "training":
            blocked_training.append(a.name)
    score = num / den if den else 1.0
    res.score, res.status = score, status_for(score)
    res.data = {"agents": rows}
    blocked = [r["agent"] for r in rows if not r["allowed"] and r["purpose"] != "training"]
    if not ctx.robots.ok:
        res.evidence.append(f"No robots.txt (HTTP {ctx.robots.status}); all agents allowed by default.")
    if blocked:
        res.summary = f"Blocks {len(blocked)} shopping or search agent(s): {', '.join(blocked)}."
        res.fix = ("Allow user-initiated and search agents (ChatGPT-User, OAI-SearchBot, Claude-User, "
                   "Claude-SearchBot, PerplexityBot, Perplexity-User) on product and category paths. "
                   "Training crawlers can stay blocked without hurting agent shopping.")
    else:
        res.summary = "All shopping and search agents are allowed."
    if blocked_training:
        res.evidence.append("Training crawlers blocked (a business choice, not scored): "
                            + ", ".join(blocked_training))
    return res


@check
def waf_behaviour(ctx):
    res = CheckResult("waf-agent-fetch", "access", "Live fetch as AI agents (bot protection)",
                      Status.SKIP, weight=3.0)
    targets = [ctx.pages.home] + ctx.pages.products[:1]
    base = {u: ctx.get(u, ua=BROWSER_UA, label="browser") for u in targets}
    if not any(_reachable(r) for r in base.values()):
        res.summary = ("The site blocked even a regular browser request from the scanner's network, "
                       "so agent-specific blocking can't be isolated. Re-run from another network.")
        return res
    rows, num, den = [], 0.0, 0.0
    for a in AGENTS:
        if not a.ua:
            continue
        outcomes = []
        for u in targets:
            if not _reachable(base[u]):
                continue
            r = ctx.get(u, ua=a.ua, label=a.name)
            outcomes.append(_reachable(r))
            rows.append({"agent": a.name, "url": u, "status": r.status,
                         "blocked": not _reachable(r), "error": r.error})
        ok = all(outcomes) if outcomes else True
        w = PURPOSE_WEIGHT[a.purpose] or 0.5
        num += w * ok
        den += w
    score = num / den if den else 1.0
    res.score, res.status = score, status_for(score)
    res.data = {"fetches": rows}
    blocked = sorted({r["agent"] for r in rows if r["blocked"]})
    for r in rows:
        if r["blocked"]:
            res.evidence.append(f"{r['agent']} → {r['url']} returned "
                                f"{r['status'] or r['error']} (browser got {base[r['url']].status})")
    res.summary = (f"Bot protection turned away: {', '.join(blocked)}." if blocked
                   else "Every agent user-agent got the same page a browser gets.")
    if blocked:
        res.fix = ("Bot protection (WAF/CDN) is blocking agents that robots.txt may allow. Add verified-bot "
                   "allow rules for AI search and user agents, using the vendors' published IP ranges.")
    res.evidence.append("Note: this test sends the agents' user-agent strings from the scanner's IP. "
                        "Real agents may be treated differently if the WAF verifies IP ranges.")
    return res


def _reachable(r) -> bool:
    if r.status is None or r.status in (401, 403, 406, 429, 451, 503):
        return False
    if r.status >= 400:
        return False
    return not CHALLENGE_MARKERS.search(r.text[:20000])


@check
def llms_txt(ctx):
    r = ctx.get(ctx.abs("/llms.txt"), accept="text/plain,text/markdown,*/*")
    res = CheckResult("llms-txt", "access", "llms.txt guide for language models", Status.FAIL, weight=0.5)
    looks_md = r.ok and r.text.lstrip().startswith("#") and "<html" not in r.text[:500].lower()
    if looks_md:
        res.status, res.score = Status.PASS, 1.0
        res.summary = f"llms.txt present ({len(r.text.splitlines())} lines)."
    else:
        res.summary = "No llms.txt found."
        res.fix = ("Optional and low-cost: publish /llms.txt listing key categories, policies and feeds. "
                   "Adoption by AI platforms is still uneven, so this is weighted lightly.")
    return res


def host(u: str) -> str:
    return urlparse(u).netloc
