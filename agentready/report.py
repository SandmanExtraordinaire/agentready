"""Write the client-facing HTML report and a machine-readable JSON file."""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import ScanResult, Status
from .scoring import fix_priority, layer_meta, tier_names

STATUS_LABEL = {"pass": "Pass", "partial": "Partial", "fail": "Fail", "info": "Info", "skip": "Not run"}
_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html", "j2"]), trim_blocks=True, lstrip_blocks=True)


def top_fixes(result: ScanResult, n: int = 6) -> list:
    candidates = [f for f in result.findings if f.fix and f.status in (Status.FAIL, Status.PARTIAL)]
    out, seen = [], set()
    for f in sorted(candidates, key=fix_priority, reverse=True):
        if f.fix not in seen:          # several findings can share one fix (e.g. "publish a UCP profile")
            seen.add(f.fix)
            out.append(f)
    return out[:n]


def render_html(results: list[ScanResult]) -> str:
    main, competitors = results[0], results[1:]
    return _env.get_template("report.html.j2").render(
        main=main, competitors=competitors, all_results=results,
        tiers=tier_names(), layers=layer_meta(), fixes=top_fixes(main), status_label=STATUS_LABEL,
    )


def write(results: list[ScanResult], out_dir: Path, stem: str | None = None) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = stem or results[0].domain.replace(":", "_")
    html_path = out_dir / f"{stem}.html"
    json_path = out_dir / f"{stem}.json"
    html_path.write_text(render_html(results), encoding="utf-8")
    json_path.write_text(json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")
    return html_path, json_path
