"""Turn findings into layer scores, an overall score and a maturity tier."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .models import STATUS_CREDIT, Finding, ScanResult, Status

RUBRIC_PATH = Path(__file__).parent / "rubric.yaml"


@lru_cache(maxsize=1)
def rubric() -> dict:
    return yaml.safe_load(RUBRIC_PATH.read_text())


def _cond_met(cond: dict, by_id: dict[str, Finding]) -> bool:
    if "any" in cond:
        return any(_cond_met(c, by_id) for c in cond["any"])
    return all(
        (f := by_id.get(fid)) is not None and f.status.value in allowed
        for fid, allowed in cond.items()
    )


def _describe(cond: dict, by_id: dict[str, Finding]) -> str:
    if "any" in cond:
        return " or ".join(_describe(c, by_id) for c in cond["any"])
    parts = []
    for fid in cond:
        f = by_id.get(fid)
        parts.append(f"'{f.title if f else fid}' ({f.status.value if f else 'not run'})")
    return ", ".join(parts)


def score(result: ScanResult) -> ScanResult:
    r = rubric()
    by_id = {f.id: f for f in result.findings}

    total_w, total = 0.0, 0.0
    for key, layer in r["layers"].items():
        got = possible = 0.0
        for fid, w in layer["findings"].items():
            f = by_id.get(fid)
            if f is None or f.status not in STATUS_CREDIT:
                continue
            possible += w
            got += w * STATUS_CREDIT[f.status]
        if possible:
            pct = 100 * got / possible
            result.layer_scores[key] = pct
            total += pct * layer["weight"]
            total_w += layer["weight"]
        else:
            result.notes.append(f"{layer['name']} was not scored (checks skipped).")
    result.score = total / total_w if total_w else 0.0

    tiers = r["tiers"]
    reached, reason = 0, ""
    for i, tier in enumerate(tiers[1:], start=1):
        unmet = [c for c in tier["when"] if not _cond_met(c, by_id)]
        if unmet:
            reason = f"Not yet {tier['name']}: needs " + "; ".join(_describe(c, by_id) for c in unmet) + "."
            break
        reached = i
    result.tier_index = reached
    result.tier = tiers[reached]["name"]
    result.tier_reason = reason or "Meets every tier."
    return result


def tier_names() -> list[dict]:
    return [{"name": t["name"], "meaning": t["meaning"]} for t in rubric()["tiers"]]


def layer_meta() -> dict:
    return {k: {"name": v["name"], "question": v["question"], "weight": v["weight"]}
            for k, v in rubric()["layers"].items()}


def fix_priority(f: Finding) -> float:
    """Higher = fix first. Weight of the finding × layer weight × points lost."""
    r = rubric()
    layer = r["layers"].get(f.layer, {})
    w = layer.get("findings", {}).get(f.id, 0)
    lost = 1 - STATUS_CREDIT.get(f.status, 1)
    return w * layer.get("weight", 0) * lost if f.status in (Status.FAIL, Status.PARTIAL) else 0
