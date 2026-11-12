"""A small, polite HTTP client: one connection pool, a delay between
requests to the same host, a response cache and a size cap."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .agents import SCANNER_UA

MAX_BYTES = 3_000_000
CHALLENGE_MARKERS = (
    "just a moment...", "cf-chl", "challenge-platform", "attention required",
    "access denied", "are you a robot", "captcha", "px-captcha", "_incapsula_",
    "request unsuccessful", "pardon our interruption",
)


@dataclass
class Response:
    url: str
    final_url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    error: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    def looks_like_challenge(self) -> bool:
        """True when the body/headers look like a bot wall rather than content."""
        if self.headers.get("cf-mitigated", "").lower() == "challenge":
            return True
        head = self.text[:6000].lower()
        return any(m in head for m in CHALLENGE_MARKERS) and len(self.text) < 60_000


class Fetcher:
    def __init__(self, delay: float = 0.6, timeout: float = 15.0, verify: bool = True):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._cache: dict[tuple[str, str, str], Response] = {}
        self.request_count = 0
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            verify=verify,
            headers={"Accept-Language": "en", "Accept": "*/*"},
        )

    def close(self) -> None:
        self.client.close()

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.delay:
                time.sleep(self.delay - gap)
        self._last[host] = time.monotonic()

    def post_json(self, url: str, payload: dict, extra_headers: dict | None = None,
                  ua: str = SCANNER_UA) -> Response:
        """Uncached JSON POST (used only for the MCP initialize handshake)."""
        self._wait(urlparse(url).netloc)
        self.request_count += 1
        headers = {"User-Agent": ua, "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream", **(extra_headers or {})}
        start = time.monotonic()
        try:
            r = self.client.post(url, json=payload, headers=headers)
            resp = Response(url=url, final_url=str(r.url), status=r.status_code,
                            headers={k.lower(): v for k, v in r.headers.items()},
                            text=r.text[:MAX_BYTES])
        except httpx.HTTPError as e:
            resp = Response(url=url, final_url=url, status=None, error=f"{type(e).__name__}: {e}")
        resp.elapsed_ms = int((time.monotonic() - start) * 1000)
        return resp

    def get(self, url: str, ua: str = SCANNER_UA, accept: str | None = None,
            method: str = "GET") -> Response:
        key = (method, url, ua)
        if key in self._cache:
            return self._cache[key]
        self._wait(urlparse(url).netloc)
        self.request_count += 1
        headers = {"User-Agent": ua}
        if accept:
            headers["Accept"] = accept
        start = time.monotonic()
        try:
            with self.client.stream(method, url, headers=headers) as r:
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                body = b"".join(chunks)
                enc = r.encoding or "utf-8"
                text = body.decode(enc, errors="replace")
                resp = Response(
                    url=url, final_url=str(r.url), status=r.status_code,
                    headers={k.lower(): v for k, v in r.headers.items()},
                    text=text,
                )
        except httpx.HTTPError as e:
            resp = Response(url=url, final_url=url, status=None, error=f"{type(e).__name__}: {e}")
        resp.elapsed_ms = int((time.monotonic() - start) * 1000)
        self._cache[key] = resp
        return resp
