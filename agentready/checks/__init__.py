"""Check registry. Each module registers functions with @check; a check
takes the ScanContext and returns a list of Findings. Adding a new check
is one function in one file — no other wiring needed."""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..discover import Discovery
from ..http import Fetcher
from ..models import Finding, Page, Status


@dataclass
class ScanContext:
    fetcher: Fetcher
    discovery: Discovery
    browser: Any = None          # agentready.browser.Browser, or None when unavailable
    browser_error: str = ""
    shared: dict[str, Any] = field(default_factory=dict)

    @property
    def base(self) -> str:
        return self.discovery.base_url

    def pages(self, kind: str | None = None) -> list[Page]:
        return [p for p in self.discovery.pages if kind is None or p.kind == kind]


CheckFn = Callable[[ScanContext], list[Finding]]
_REGISTRY: list[tuple[str, CheckFn]] = []


def check(layer: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        _REGISTRY.append((layer, fn))
        return fn
    return deco


def run_all(ctx: ScanContext) -> list[Finding]:
    # Import order = run order. Later checks may read ctx.shared from earlier ones.
    from . import access, protocols, interop, discoverability, rendering, task  # noqa: F401

    findings: list[Finding] = []
    for layer, fn in _REGISTRY:
        try:
            findings.extend(fn(ctx))
        except Exception as e:  # a broken check must never sink the whole scan
            findings.append(Finding(
                id=f"{fn.__name__}_error", layer=layer, title=f"{fn.__name__} could not run",
                status=Status.SKIP, summary=f"Internal error: {e}",
                evidence=[traceback.format_exc(limit=2)],
            ))
    return findings
