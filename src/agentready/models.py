"""Core data types shared by checks, scoring and reports."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    INFO = "info"      # observed, not scored (e.g. inferred ACP signals)
    SKIP = "skip"      # could not run (no browser, no pages found)


# Layers in report order: key -> (display name, share of overall score).
LAYERS = {
    "access": ("Agent access", 0.25),
    "aeo": ("Structured data (AEO/GEO)", 0.20),
    "rendering": ("Content without JavaScript", 0.15),
    "ucp": ("UCP protocol", 0.15),
    "acp": ("ACP signals", 0.0),
    "interop": ("Agent-to-agent", 0.10),
    "task": ("Agent task completion", 0.15),
}


@dataclass
class CheckResult:
    id: str
    layer: str
    title: str
    status: Status
    score: float = 0.0           # 0..1, ignored for INFO/SKIP
    weight: float = 1.0
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    fix: str = ""
    data: dict = field(default_factory=dict)

    @property
    def scored(self) -> bool:
        return self.status not in (Status.INFO, Status.SKIP)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def status_for(score: float) -> Status:
    if score >= 0.85:
        return Status.PASS
    if score >= 0.35:
        return Status.PARTIAL
    return Status.FAIL
