"""Check registry. Each check is a function (ctx) -> CheckResult | list[CheckResult].

To add a check: write a function in any module here, decorate it with @check,
and import the module at the bottom of this file. Nothing else changes.
"""
from __future__ import annotations

from typing import Callable

REGISTRY: list[Callable] = []


def check(fn: Callable) -> Callable:
    REGISTRY.append(fn)
    return fn


# Order matters: later checks read ctx.shared written by earlier ones.
from . import access, rendering, aeo, ucp, acp, interop, task  # noqa: E402,F401
