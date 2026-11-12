"""Minimal, read-only MCP probe: `initialize`, then `tools/list`.
Never calls a tool. Handles plain JSON and single-event SSE responses."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .http import Fetcher, Response

PROTOCOL_VERSION = "2025-06-18"


@dataclass
class McpProbe:
    endpoint: str
    reachable: bool = False
    is_mcp: bool = False
    auth_required: bool = False
    server_name: str = ""
    tools: list[str] = field(default_factory=list)
    detail: str = ""


def _parse(resp: Response) -> dict | None:
    text = resp.text.strip()
    if not text:
        return None
    if "text/event-stream" in resp.headers.get("content-type", "") or text.startswith(("event:", "data:")):
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def probe_mcp(fx: Fetcher, endpoint: str) -> McpProbe:
    p = McpProbe(endpoint=endpoint)
    init = fx.post_json(endpoint, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                   "clientInfo": {"name": "agentready-scanner", "version": "0.1"}},
    })
    if init.status is None:
        p.detail = init.error or "no response"
        return p
    p.reachable = init.status < 500
    if init.status in (401, 403):
        p.auth_required = True
        p.is_mcp = "www-authenticate" in init.headers
        p.detail = f"HTTP {init.status}: endpoint requires authorisation"
        return p
    body = _parse(init)
    result = (body or {}).get("result") or {}
    if "serverInfo" not in result and "protocolVersion" not in result:
        p.detail = f"HTTP {init.status}: response was not an MCP initialize result"
        return p
    p.is_mcp = True
    p.server_name = (result.get("serverInfo") or {}).get("name", "")
    headers = {"MCP-Protocol-Version": result.get("protocolVersion", PROTOCOL_VERSION)}
    if sid := init.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = sid
    fx.post_json(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
    tl = fx.post_json(endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)
    tools = ((_parse(tl) or {}).get("result") or {}).get("tools") or []
    p.tools = [t.get("name", "?") for t in tools if isinstance(t, dict)][:40]
    p.detail = f"MCP server '{p.server_name or 'unnamed'}' exposes {len(p.tools)} tools"
    return p
