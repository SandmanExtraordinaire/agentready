"""Data models shared by the scanner, checks, scoring and report."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    INFO = "info"      # reported, not scored
    SKIP = "skip"      # could not run (e.g. no browser installed)


# Points awarded per status, as a fraction of the finding's weight.
STATUS_CREDIT = {Status.PASS: 1.0, Status.PARTIAL: 0.5, Status.FAIL: 0.0}


@dataclass
class Finding:
    id: str                    # stable id, matches rubric.yaml
    layer: str                 # access | protocols | interop | discoverability | rendering | task
    title: str                 # plain-language name shown in the report
    status: Status
    summary: str               # one sentence: what we found
    evidence: list[str] = field(default_factory=list)   # URLs, status codes, snippets
    fix: str = ""              # what the client should do
    confidence: str = "verified"   # verified | inferred
    data: dict[str, Any] = field(default_factory=dict)  # machine-readable extras

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Page:
    url: str
    kind: str                  # home | category | product | cart | other
    status: int | None = None
    html: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    final_url: str = ""
    error: str = ""


@dataclass
class ScanResult:
    domain: str
    base_url: str
    started_at: str
    finished_at: str = ""
    pages: list[Page] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    layer_scores: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    tier: str = ""
    tier_index: int = 0
    tier_reason: str = ""
    notes: list[str] = field(default_factory=list)
    ucp_schema_version: str = ""

    def finding(self, fid: str) -> Finding | None:
        return next((f for f in self.findings if f.id == fid), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "base_url": self.base_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "score": round(self.score, 1),
            "tier": self.tier,
            "tier_index": self.tier_index,
            "tier_reason": self.tier_reason,
            "layer_scores": {k: round(v, 1) for k, v in self.layer_scores.items()},
            "ucp_schema_version": self.ucp_schema_version,
            "notes": self.notes,
            "pages": [
                {"url": p.url, "kind": p.kind, "status": p.status, "error": p.error}
                for p in self.pages
            ],
            "findings": [f.to_dict() for f in self.findings],
        }
