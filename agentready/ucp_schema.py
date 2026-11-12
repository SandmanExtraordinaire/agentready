"""Validate a /.well-known/ucp business profile against the official UCP
JSON Schemas, vendored per release under schemas/ucp/<version>/ by
scripts/sync_ucp_schemas.py. A profile is validated against the version it
declares; unknown versions fall back to the newest release we have."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

SCHEMA_ROOT = Path(__file__).parent / "schemas" / "ucp"


def available_versions() -> list[str]:
    if not SCHEMA_ROOT.exists():
        return []
    return sorted(p.name for p in SCHEMA_ROOT.iterdir() if p.is_dir())


def latest_version() -> str:
    versions = available_versions()
    return versions[-1] if versions else ""


@lru_cache(maxsize=8)
def _validator(version: str) -> Draft202012Validator:
    root = SCHEMA_ROOT / version
    files = {f.relative_to(root).as_posix(): f for f in root.rglob("*.json")}

    resources = []
    for f in files.values():
        doc = json.loads(f.read_text())
        if "$id" in doc:
            resources.append((doc["$id"], Resource.from_contents(doc)))

    def retrieve(uri: str) -> Resource:
        # Older releases mix $id URLs with file-path refs ("../services/x.json").
        # Resolve anything unknown by the longest matching path suffix.
        parts = [p for p in urlparse(uri).path.split("/") if p]
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            hits = [f for rel, f in files.items() if rel == suffix or rel.endswith("/" + suffix)]
            if len(hits) == 1:
                return Resource.from_contents(json.loads(hits[0].read_text()))
        raise NoSuchResource(ref=uri)

    registry = Registry(retrieve=retrieve).with_resources(resources)

    legacy = root / "discovery" / "profile_schema.json"
    if legacy.exists():                       # releases up to 2026-04-08
        doc = json.loads(legacy.read_text())
        ref = doc["$id"]
        if "business_profile" in doc.get("$defs", {}):
            ref += "#/$defs/business_profile"
        entry = {"$ref": ref}
    else:                                     # 2026-08-25 onwards
        entry = {"allOf": [
            {"$ref": "https://ucp.dev/schemas/profile.json"},
            {"properties": {"ucp": {"$ref": "https://ucp.dev/schemas/ucp.json#/$defs/business_schema"}}},
        ]}
    return Draft202012Validator(entry, registry=registry)


def validate_profile(profile: dict) -> tuple[str, list[str]]:
    """Returns (schema_version_used, list_of_error_messages)."""
    declared = str((profile.get("ucp") or {}).get("version", "")) if isinstance(profile, dict) else ""
    versions = available_versions()
    if not versions:
        return "", ["No UCP schemas vendored; run scripts/sync_ucp_schemas.py"]
    version = declared if declared in versions else versions[-1]
    errors: list[str] = []
    try:
        found = sorted(_validator(version).iter_errors(profile), key=lambda e: list(e.path))
    except Exception as e:  # unresolvable ref etc. — report, don't crash
        return version, [f"Schema could not be evaluated: {type(e).__name__}: {e}"]
    for e in found:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        msg = e.message if len(e.message) < 220 else e.message[:217] + "..."
        line = f"{where}: {msg}"
        if line not in errors:
            errors.append(line)
        if len(errors) >= 10:
            break
    return version, errors
