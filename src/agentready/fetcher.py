"""Polite HTTP fetching with agent user-agent profiles and a request log."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from . import __version__

SCANNER_UA = f"AgentReadyScanner/{__version__} (+https://github.com/; readiness audit)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Agent:
    name: str          # robots.txt token
    owner: str
    purpose: str       # "user" (acts for a shopper), "search", "training"
    ua: str | None     # full UA string for live fetch tests; None = robots-only token


# Purpose drives scoring: blocking a "training" crawler is a legitimate business
# choice and is reported, not penalised. Blocking "user"/"search" agents costs
# visibility and transactions.
AGENTS: list[Agent] = [
    Agent("ChatGPT-User", "OpenAI", "user",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot"),
    Agent("OAI-SearchBot", "OpenAI", "search",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"),
    Agent("GPTBot", "OpenAI", "training",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot"),
    Agent("Claude-User", "Anthropic", "user",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Claude-User/1.0; +Claude-User@anthropic.com"),
    Agent("Claude-SearchBot", "Anthropic", "search",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Claude-SearchBot/1.0; +Claude-SearchBot@anthropic.com"),
    Agent("ClaudeBot", "Anthropic", "training",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +claudebot@anthropic.com"),
    Agent("PerplexityBot", "Perplexity", "search",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot"),
    Agent("Perplexity-User", "Perplexity", "user",
          "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user"),
    Agent("Googlebot", "Google", "search", None),          # do not spoof Googlebot
    Agent("Google-Extended", "Google", "training", None),  # robots token only
    Agent("Bingbot", "Microsoft", "search", None),
    Agent("Applebot-Extended", "Apple", "training", None),
    Agent("Amazonbot", "Amazon", "search", None),
    Agent("meta-externalagent", "Meta", "training", None),
]


@dataclass
class Response:
    url: str
    final_url: str
    status: int | None
    headers: dict
    text: str
    elapsed_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    def json(self):
        import json
        return json.loads(self.text)


@dataclass
class Fetcher:
    delay: float = 0.4
    max_requests: int = 120
    timeout: float = 15.0
    log: list[dict] = field(default_factory=list)
    _cache: dict = field(default_factory=dict)
    _last: float = 0.0

    def __post_init__(self):
        self.client = httpx.Client(follow_redirects=True, timeout=self.timeout, verify=True)

    def close(self):
        self.client.close()

    def get(self, url: str, ua: str = SCANNER_UA, label: str = "scanner",
            accept: str = "text/html,application/json;q=0.9,*/*;q=0.8") -> Response:
        key = (url, ua, accept)
        if key in self._cache:
            return self._cache[key]
        if len(self.log) >= self.max_requests:
            r = Response(url, url, None, {}, "", 0, "request budget exhausted")
            self._cache[key] = r
            return r
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        start = time.monotonic()
        try:
            resp = self.client.get(url, headers={"User-Agent": ua, "Accept": accept})
            r = Response(url, str(resp.url), resp.status_code, dict(resp.headers),
                         resp.text[:3_000_000], int((time.monotonic() - start) * 1000))
        except httpx.HTTPError as e:
            r = Response(url, url, None, {}, "", int((time.monotonic() - start) * 1000),
                         f"{type(e).__name__}: {e}")
        self._last = time.monotonic()
        self.log.append({"url": url, "as": label, "status": r.status,
                         "ms": r.elapsed_ms, "error": r.error})
        self._cache[key] = r
        return r


def origin(url: str) -> str:
    p = urlparse(url if "://" in url else f"https://{url}")
    return f"{p.scheme}://{p.netloc}"
