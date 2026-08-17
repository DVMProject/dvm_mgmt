#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#/*
#* Digital Voice Modem - Management CLI
#* GPLv2 Open Source. Use is subject to license terms.
#* DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#*
#*  Copyright (C) 2026 DVMProject Authors
#*
#*/
"""
DVM Management Web Interface - HTMX API Routes

All endpoints return HTML fragments consumed by HTMX.
"""

import asyncio
import csv
from datetime import datetime, timedelta
import glob
import html
import json
import os
import re
import shlex
import subprocess
import sys
from collections import deque
from urllib.parse import parse_qs
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from markupsafe import Markup

from dvm_mgmt.core.api_client import DVMAPIClient
from dvm_mgmt.core.config import ConsoleConfig
from dvm_mgmt.core.config_file_manager import ConfigFileManager
from dvm_mgmt.core.process_manager import ProcessManager
from dvm_mgmt.operations.peers import PeerManager
from dvm_mgmt.operations.radio_ids import RadioIDManager
from dvm_mgmt.operations.talkgroups import TalkgroupManager
from dvm_mgmt.web.federation import FederationManager

router = APIRouter()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?)")
_RID_RE = re.compile(r"\bRID[:=\s]+(\d+)\b", re.IGNORECASE)
_TG_RE = re.compile(r"\bTG(?:ID)?[:=\s]+(\d+)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(request: Request) -> ConsoleConfig:
    """Return app-wide console configuration from request state."""
    return request.app.state.config


def _fed(request: Request) -> FederationManager:
    """Return the shared federation manager bound to the application."""
    return request.app.state.federation


def _selected_target(request: Request):
    """Resolve the active federation target for this incoming request."""
    return _fed(request).selected_target_from_request(request)


def _proxied_request_path(request: Request) -> str:
    """Return a root-path-normalized path suitable for remote proxying."""
    path = request.url.path
    root_path = str(request.scope.get("root_path") or request.app.root_path or "")
    if not root_path or root_path == "/":
        return path
    if path == root_path:
        return "/"
    if path.startswith(root_path + "/"):
        return path[len(root_path):]
    return path


def _proxy_headers(upstream_headers) -> dict:
    """Filter upstream response headers to a safe passthrough subset."""
    copied = {}
    allowed = {
        "content-type",
        "content-disposition",
        "cache-control",
        "hx-trigger",
        "hx-redirect",
        "etag",
        "last-modified",
    }
    for key, value in upstream_headers.items():
        if key.lower() in allowed:
            copied[key] = value
    return copied


async def _proxy_if_remote(request: Request):
    """Forward the request to the selected remote federation target when needed."""
    target = _selected_target(request)
    if target.is_local:
        return None

    fed = _fed(request)
    body = await request.body()
    query = dict(request.query_params.multi_items())
    accept = request.headers.get("accept", "*/*")
    content_type = request.headers.get("content-type", "")
    upstream = await asyncio.to_thread(
        fed.proxy_request,
        target,
        request.method,
        _proxied_request_path(request),
        query,
        body,
        content_type,
        accept,
        False,
    )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_proxy_headers(upstream.headers),
        media_type=upstream.headers.get("content-type"),
    )


def _t(request: Request):
    """Return the template environment stored on app state."""
    return request.app.state.templates


def _frag(request: Request, template: str, ctx: dict) -> HTMLResponse:
    """Render a template fragment response with request injected into context."""
    ctx["request"] = request
    return _t(request).TemplateResponse(template, ctx)


def _toast(message: str, kind: str = "success") -> dict:
    """Build HX-Trigger header value for toast notification."""
    import json
    return {"HX-Trigger": json.dumps({"showToast": {"message": message, "type": kind}})}


def _ok(message: str) -> Response:
    """Return a success response carrying a toast notification header."""
    return Response(status_code=200, headers=_toast(message))


def _err(message: str) -> Response:
    """Return an error response carrying a toast notification header."""
    return Response(status_code=200, headers=_toast(message, "error"))


def _resolve_log_source(cfg: ConsoleConfig, log_type: str) -> tuple[Path, str]:
    """Resolve the backing log file and prefix mode for a web log type."""
    normalized = log_type.replace("-", "_")

    if normalized in ("system", "fne"):
        return Path(cfg.log_file), normalized
    else:
        raise ValueError(f"Unknown log type: {log_type}")

    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"Log file not found for pattern: {pattern}")

    newest = max(matches, key=lambda p: Path(p).stat().st_mtime)
    return Path(newest), normalized


def _line_matches_prefix(line: str, mode: str, cfg: ConsoleConfig) -> bool:
    """Return whether a log line belongs to the selected logical log stream."""
    if mode == "system":
        return cfg.log_prefix_system in line
    if mode == "fne":
        return cfg.log_prefix_system in line
    return True


def _tail_filtered_lines(
    path: Path,
    limit: int,
    matches,
    regex: Optional[re.Pattern],
    max_bytes: int = 8 * 1024 * 1024,
) -> list[str]:
    """Read from file end in chunks and keep only matching lines.

    This avoids scanning very large logs from start, which was causing UI hangs.
    """
    if limit <= 0:
        return []

    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    kept: deque[str] = deque(maxlen=limit)
    chunk_size = 64 * 1024

    with path.open("rb") as fh:
        fh.seek(0, 2)
        file_size = fh.tell()
        pos = file_size
        buffer = b""
        bytes_read = 0

        while pos > 0 and bytes_read < max_bytes:
            read_size = chunk_size if pos >= chunk_size else pos
            pos -= read_size
            fh.seek(pos)
            chunk = fh.read(read_size)
            bytes_read += read_size
            buffer = chunk + buffer

            if b"\n" not in buffer and pos > 0:
                continue

            parts = buffer.split(b"\n")
            buffer = parts[0]

            for raw in reversed(parts[1:]):
                line = raw.decode("utf-8", errors="ignore").rstrip("\r")
                if not line:
                    continue
                if not matches(line):
                    continue
                if regex and not regex.search(line):
                    continue
                kept.appendleft(line)
                if len(kept) >= limit:
                    return list(kept)

        if buffer:
            line = buffer.decode("utf-8", errors="ignore").rstrip("\r")
            if line and matches(line) and (not regex or regex.search(line)):
                kept.appendleft(line)

    return list(kept)


def _format_log_line_html(line: str) -> Markup:
    """Convert a raw log line to syntax-highlighted safe HTML markup."""
    clean = _ANSI_RE.sub("", line)
    prefix = ""
    rest = clean

    prefix_match = re.match(
        r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?)(\s+)([A-Za-z]:)(\s*)(.*)$",
        clean,
    )
    if prefix_match:
        ts, sep, level, post, tail = prefix_match.groups()
        level_up = level.upper()
        if level_up == "W:":
            pclass = "text-amber-300 font-semibold"
        elif level_up == "E:":
            pclass = "text-red-300 font-semibold"
        elif level_up == "I:":
            pclass = "text-slate-400"
        elif level_up == "D:":
            pclass = "text-blue-300 font-semibold"
        elif level_up == "U:":
            pclass = "text-emerald-300 font-semibold"
        else:
            pclass = "text-slate-300"
        prefix = f'<span class="{pclass}">{html.escape(ts + sep + level)}</span>{html.escape(post)}'
        rest = tail
    else:
        level_match = re.match(r"^([A-Za-z]:)(\s*)(.*)$", clean)
        if level_match:
            level, post, tail = level_match.groups()
            level_up = level.upper()
            if level_up == "W:":
                pclass = "text-amber-300 font-semibold"
            elif level_up == "E:":
                pclass = "text-red-300 font-semibold"
            elif level_up == "I:":
                pclass = "text-slate-400"
            elif level_up == "D:":
                pclass = "text-blue-300 font-semibold"
            elif level_up == "U:":
                pclass = "text-emerald-300 font-semibold"
            else:
                pclass = "text-slate-300"
            prefix = f'<span class="{pclass}">{html.escape(level)}</span>{html.escape(post)}'
            rest = tail

    rendered = html.escape(rest)
    rendered = _RID_RE.sub(r'RID <span class="text-emerald-300">\1</span>', rendered)
    rendered = _TG_RE.sub(r'TG <span class="text-indigo-300">\1</span>', rendered)
    rendered = re.sub(r"\b(connected|registered|online|accepted|linked)\b", r'<span class="text-emerald-300">\1</span>', rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\b(failed|denied|exception|error|unauthorized|disconnect(?:ed)?)\b", r'<span class="text-red-300">\1</span>', rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\b(net)\b", r'<span class="text-cyan-300">\1</span>', rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"\b(STUN|CSBK)\b", r'<span class="text-fuchsia-300">\1</span>', rendered)
    rendered = re.sub(r"\b(TERMINATOR_WITH_LC|TERMINATOR|TX_REL)\b", r'<span class="text-emerald-300">\1</span>', rendered)
    rendered = re.sub(r"\b(LDU|HDU|VOICE|VCALL)\b", r'<span class="text-cyan-700">\1</span>', rendered)
    rendered = re.sub(r"\bMSTR\b", r'<span class="text-blue-300 font-semibold">MSTR</span>', rendered)
    rendered = re.sub(r"\bPEER\b", r'<span class="text-cyan-300 font-semibold">PEER</span>', rendered)
    rendered = re.sub(r"\bSTP\b", r'<span class="text-emerald-300 font-semibold">STP</span>', rendered)
    rendered = re.sub(r"\bREPL\b", r'<span class="text-amber-300 font-semibold">REPL</span>', rendered)
    rendered = re.sub(r"\bNAK\b", r'<span class="text-red-300 font-semibold">NAK</span>', rendered)

    # Protocol suffix coloring: from token to end-of-line.
    suffix_match = re.search(r"\b(LDU1|LDU2|TSDU|TDU)\b", rendered, flags=re.IGNORECASE)
    if suffix_match:
      token = suffix_match.group(1).upper()
      if token in ("LDU1", "LDU2"):
          suffix_class = "text-cyan-700"
      elif token == "TSDU":
          suffix_class = "text-fuchsia-300"
      else:
          suffix_class = "text-emerald-300"
      rendered = rendered[:suffix_match.start()] + f'<span class="{suffix_class}">' + rendered[suffix_match.start():] + "</span>"

    if not prefix and not rendered:
        return Markup('<span class="text-slate-400"></span>')
    if not prefix:
        return Markup(f'<span class="text-slate-300">{rendered}</span>')
    return Markup(prefix + rendered)


def _read_web_logs(
    cfg: ConsoleConfig,
    log_type: str,
    lines: int,
    filter_pattern: Optional[str] = None,
) -> list[str]:
    """Read and filter log lines for the web UI log viewer endpoint."""
    path, mode = _resolve_log_source(cfg, log_type)
    regex = re.compile(filter_pattern, re.IGNORECASE) if filter_pattern else None

    return _tail_filtered_lines(
        path,
        lines,
        lambda line: _line_matches_prefix(line, mode, cfg),
        regex,
    )


def _normalize_connected_peers(result: dict) -> list[dict[str, Any]]:
    """Normalize peer list payloads returned by different FNE command variants."""
    if not isinstance(result, dict):
        return []

    raw_peers = result.get("peers")
    if raw_peers is None and isinstance(result.get("data"), dict):
        raw_peers = result["data"].get("peers")
    if raw_peers is None:
        raw_peers = result.get("peerList")
    if not isinstance(raw_peers, list):
        return []

    normalized: list[dict[str, Any]] = []
    for peer in raw_peers:
        if not isinstance(peer, dict):
            continue
        cfg = peer.get("config", {}) if isinstance(peer.get("config"), dict) else {}
        peer_id = peer.get("peerId")
        if peer_id is None:
            peer_id = peer.get("peer_id", peer.get("id"))
        identity = peer.get("identity") or cfg.get("identity")
        address = peer.get("address") or peer.get("ipAddress") or peer.get("ip")
        port = peer.get("port")
        link_peer_id = peer.get("linkPeerId", peer.get("parentPeerId"))
        master_peer_id = peer.get("masterPeerId") or cfg.get("masterPeerId")
        software = peer.get("software") or cfg.get("software")

        sysview = bool(peer.get("sysView", cfg.get("sysView", False)))
        external_peer = bool(peer.get("externalPeer", cfg.get("externalPeer", False)))
        replica_peer = bool(peer.get("replica", cfg.get("replica", False)))
        conventional_peer = bool(peer.get("conventionalPeer", cfg.get("conventionalPeer", False)))
        console_peer = bool(peer.get("consolePeer", cfg.get("consolePeer", False)))

        if not identity:
            identity = cfg.get("peerAlias") or cfg.get("alias")
        connected = peer.get("connected")
        if connected is None:
            state = str(peer.get("state", "")).strip().lower()
            connected = state in ("connected", "up", "online", "1", "true")

        normalized.append({
            "peerId": peer_id,
            "identity": identity,
            "address": address,
            "port": port,
            "connected": bool(connected),
            "linkPeerId": link_peer_id,
            "masterPeerId": master_peer_id,
            "software": software,
            "sysView": sysview,
            "externalPeer": external_peer,
            "replica": replica_peer,
            "conventionalPeer": conventional_peer,
            "consolePeer": console_peer,
        })

    return normalized


def _as_bool(value: Any) -> bool:
    """Parse common truthy representations used by form and YAML data."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on", "x")


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    """Convert a value to int and clamp it to an inclusive numeric range."""
    try:
        iv = int(value)
    except Exception:
        iv = default
    if iv < low:
        return low
    if iv > high:
        return high
    return iv


# ---------------------------------------------------------------------------
# Status / Dashboard
# ---------------------------------------------------------------------------

@router.get("/config-files")
async def list_config_files(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    return JSONResponse({"files": [
        {"id": item.id, "name": item.name, "path": str(item.path), "format": item.format}
        for item in _cfg(request).editable_config_files
    ]})


@router.get("/config-files/{file_id}")
async def get_config_file(request: Request, file_id: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    manager = ConfigFileManager(_cfg(request))
    try:
        item, content = manager.read(file_id)
        backups = manager.backups(file_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to read configuration: {exc}") from exc
    return JSONResponse({
        "id": item.id, "name": item.name, "path": str(item.path), "format": item.format,
        "content": content,
        "backups": [{"name": path.name, "created": datetime.fromtimestamp(
            path.stat().st_mtime).isoformat(timespec="seconds")} for path in backups],
    })


@router.put("/config-files/{file_id}")
async def save_config_file(request: Request, file_id: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    manager = ConfigFileManager(_cfg(request))
    try:
        payload = await request.json()
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            raise ValueError("The request must contain configuration text in 'content'")
        backup = manager.save(file_id, content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to save configuration: {exc}") from exc
    return JSONResponse({"message": "Configuration saved", "backup": backup.name})


@router.post("/config-files/{file_id}/restore/{backup_name}")
async def restore_config_file(request: Request, file_id: str, backup_name: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    manager = ConfigFileManager(_cfg(request))
    try:
        safety_backup = manager.restore(file_id, backup_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Unable to restore configuration: {exc}") from exc
    return JSONResponse({"message": "Configuration restored", "backup": safety_backup.name})


@router.delete("/config-files/{file_id}/revisions/{backup_name}")
async def delete_config_revision(request: Request, file_id: str, backup_name: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    manager = ConfigFileManager(_cfg(request))
    try:
        deleted = manager.delete_backup(file_id, backup_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to delete configuration revision: {exc}") from exc
    return JSONResponse({"message": "Configuration revision deleted", "revision": deleted.name})


@router.get("/status", response_class=HTMLResponse)
async def get_status(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    proc_mgr = ProcessManager()
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )

    services = await asyncio.to_thread(proc_mgr.get_all_services)
    stats_raw = await asyncio.to_thread(api_client.get_stats)
    stats = stats_raw if stats_raw.get("success", True) else {}

    try:
        span_raw = await asyncio.to_thread(api_client.call, "fne-spanning-tree")
        spanning_tree = span_raw.get("masterTree", []) if span_raw.get("success", True) else []
    except Exception:
        spanning_tree = []

    return _frag(request, "fragments/status.html", {
        "services": services,
        "stats": stats,
        "spanning_tree": spanning_tree,
        "system_watch_enabled": cfg.system_watch_enabled,
    })


@router.get("/affiliations", response_class=HTMLResponse)
async def get_affiliations(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )

    try:
        result = await asyncio.to_thread(api_client.call, "fne-affs")
        affiliations = result.get("affiliations", []) if result.get("success", True) else []
    except Exception:
        affiliations = []

    # Build lookup dicts for name resolution (best-effort, never fatal)
    rid_names: dict = {}
    tg_names: dict = {}
    try:
        rid_path = cfg.system_rid_acl_file
        if rid_path and rid_path.exists():
            import csv as _csv
            with open(rid_path, newline="") as fh:
                for row in _csv.reader(fh):
                    if not row or row[0].startswith("#"):
                        continue
                    rid = row[0].strip()
                    alias = row[2].strip() if len(row) > 2 else ""
                    if alias:
                        rid_names[rid] = alias
    except Exception:
        pass
    try:
        import yaml as _yaml
        tg_path = cfg.system_tgid_acl_file
        if tg_path and tg_path.exists():
            data = _yaml.safe_load(tg_path.read_text()) or {}
            for entry in data.get("groupVoice", []):
                src = entry.get("source", {})
                tgid = str(src.get("tgid", ""))
                label = entry.get("name") or entry.get("alias") or ""
                if tgid and label:
                    tg_names[tgid] = label
    except Exception:
        pass

    return _frag(request, "fragments/affiliations.html", {
        "affiliations": affiliations,
        "rid_names": rid_names,
        "tg_names": tg_names,
    })


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------

@router.get("/connected-peers", response_class=HTMLResponse)
async def get_connected_peers(request: Request, scope: str = "system"):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    normalized_scope = (scope or "system").strip().lower()
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )

    peers = []
    try:
        # Primary command used by CLI/TUI; fallback retained for older builds.
        result = await asyncio.to_thread(api_client.call, "fne-peerlist")
        if not result.get("success", True):
            result = await asyncio.to_thread(api_client.call, "fne-peer-query")
        if result.get("success", True):
            peers = _normalize_connected_peers(result)
            peers.sort(key=lambda p: int(p.get("peerId") or 0))
    except Exception:
        pass
    return _frag(request, "fragments/connected_peers.html", {
        "peers": peers,
        "scope": normalized_scope,
    })


@router.get("/peers/{system}", response_class=HTMLResponse)
async def list_peers(request: Request, system: str):
    cfg = _cfg(request)
    mgr = PeerManager(cfg)
    peers = await asyncio.to_thread(mgr.list_peers, system)
    return _frag(request, "fragments/peer_table.html", {"peers": peers, "system": system})


@router.get("/system-watch/peer-aliases")
async def system_watch_peer_aliases(request: Request, system: str = "both"):
    cfg = _cfg(request)
    if not cfg.system_watch_enabled:
        return JSONResponse({"detail": "System Watch is disabled"}, status_code=404)

    mgr = PeerManager(cfg)

    normalized = (system or "both").strip().lower()

    aliases: dict[str, str] = {}
    try:
        peers = await asyncio.to_thread(mgr.list_peers, 'system')
    except Exception:
        return JSONResponse({"aliases": {}, "system": normalized}, status_code=400)

    for peer in peers:
        peer_id = str(peer.get("id") or "").strip()
        peer_name = str(peer.get("name") or "").strip()
        if peer_id and peer_name and peer_id not in aliases:
            aliases[peer_id] = peer_name

    return JSONResponse({
        "aliases": aliases,
        "system": normalized,
        "count": len(aliases),
    })


@router.post("/peers/{system}", response_class=HTMLResponse)
async def add_peer(
    request: Request,
    system: str,
):
    cfg = _cfg(request)
    mgr = PeerManager(cfg)
    try:
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload_data = await request.json()
            except Exception:
                payload_data = {}
        else:
            parsed_body = parse_qs(raw_body, keep_blank_values=True)
            payload_data = {key: values[-1] for key, values in parsed_body.items() if values}

        peer_id_raw = str(payload_data.get("peer_id", "") or "").strip()
        if not peer_id_raw:
            raise ValueError("Peer ID is required")
        try:
            peer_id = int(peer_id_raw)
        except Exception as exc:
            raise ValueError("Peer ID must be a number") from exc

        password = str(payload_data.get("password", "") or "").strip()

        peer_name = str(payload_data.get("peer_name", "") or "").strip()
        replica = _clamp_int(payload_data.get("replica", 0), 0, 0, 1)
        request_key = _clamp_int(payload_data.get("request_key", 0), 0, 0, 1)
        can_inhibit = _clamp_int(payload_data.get("can_inhibit", 0), 0, 0, 1)
        call_priority = _clamp_int(payload_data.get("call_priority", 0), 0, 0, 1)
        jitter = _clamp_int(payload_data.get("jitter", 360), 360, 0, 360000)
        max_size = _clamp_int(payload_data.get("max_size", 4), 4, 0, 100000)
        max_wait = _clamp_int(payload_data.get("max_wait", 40000), 40000, 0, 3600000)

        existing_peers = await asyncio.to_thread(mgr.list_peers, system)
        if any(int(p.get("id", -1)) == peer_id for p in existing_peers):
            raise ValueError(f"Duplicate peer ID: {peer_id}")

        success, msg = await asyncio.to_thread(
            mgr.add_peer, system, peer_id, password, replica,
            peer_name, request_key, can_inhibit, call_priority,
            jitter, max_size, max_wait,
        )
        if not success:
            return Response(status_code=400, headers=_toast(msg, "error"))
        peers = await asyncio.to_thread(mgr.list_peers, system)
        resp = _frag(request, "fragments/peer_table.html", {"peers": peers, "system": system})
        resp.headers["HX-Trigger"] = _toast(msg)["HX-Trigger"]
        return resp
    except ValueError as exc:
        return Response(status_code=400, headers=_toast(str(exc), "error"))


@router.put("/peers/{system}/{peer_id}", response_class=HTMLResponse)
async def update_peer(
    request: Request,
    system: str,
    peer_id: int,
):
    cfg = _cfg(request)
    mgr = PeerManager(cfg)
    try:
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                payload_data = await request.json()
            except Exception:
                payload_data = {}
        else:
            parsed_body = parse_qs(raw_body, keep_blank_values=True)
            payload_data = {key: values[-1] for key, values in parsed_body.items() if values}

        password = payload_data.get("password")
        if password is not None:
            password = str(password).strip()

        peer_name = payload_data.get("peer_name")
        if peer_name is not None:
            peer_name = str(peer_name).strip()

        def _opt_int(name: str, default: Optional[int], lo: int, hi: int) -> Optional[int]:
            if name not in payload_data:
                return default
            raw = str(payload_data.get(name, "") or "").strip()
            if raw == "":
                return default
            return _clamp_int(raw, default if default is not None else 0, lo, hi)

        replica = _opt_int("replica", None, 0, 1)
        request_key = _opt_int("request_key", None, 0, 1)
        can_inhibit = _opt_int("can_inhibit", None, 0, 1)
        call_priority = _opt_int("call_priority", None, 0, 1)
        jitter = _opt_int("jitter", None, 0, 360000)
        max_size = _opt_int("max_size", None, 0, 100000)
        max_wait = _opt_int("max_wait", None, 0, 3600000)

        success, msg = await asyncio.to_thread(
            mgr.update_peer, system, peer_id, password, replica,
            peer_name, request_key, can_inhibit, call_priority,
            jitter, max_size, max_wait,
        )
        if not success:
            return Response(status_code=400, headers=_toast(msg, "error"))

        peers = await asyncio.to_thread(mgr.list_peers, system)
        resp = _frag(request, "fragments/peer_table.html", {"peers": peers, "system": system})
        resp.headers["HX-Trigger"] = _toast(msg)["HX-Trigger"]
        return resp
    except ValueError as exc:
        return Response(status_code=400, headers=_toast(str(exc), "error"))


@router.delete("/peers/{system}/{peer_id}")
async def delete_peer(request: Request, system: str, peer_id: int):
    cfg = _cfg(request)
    mgr = PeerManager(cfg)
    success, msg = await asyncio.to_thread(mgr.remove_peer, system, peer_id)
    kind = "success" if success else "error"
    return Response(status_code=200, headers=_toast(msg, kind))


# ---------------------------------------------------------------------------
# Talkgroups and Radio IDs
# ---------------------------------------------------------------------------

def _extract_tg_entries(data: dict) -> list:
    """Extract talkgroup entries from dvmhost groupVoice talkgroup_rules YAML."""
    entries = data.get("groupVoice", [])
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        src = entry.get("source", {})
        cfg_block = entry.get("config", {})
        inclusion = cfg_block.get("inclusion", [])
        exclusion = cfg_block.get("exclusion", [])
        always = cfg_block.get("always", [])
        rid_permitted = cfg_block.get("rid_permitted", [])

        if not isinstance(inclusion, list):
            inclusion = []
        if not isinstance(exclusion, list):
            exclusion = []
        if not isinstance(always, list):
            always = []
        if not isinstance(rid_permitted, list):
            rid_permitted = []

        result.append({
            "tgid":       src.get("tgid", "—"),
            "slot":       src.get("slot", "—"),
            "name":       entry.get("name", "—"),
            "alias":      entry.get("alias", ""),
            "active":     cfg_block.get("active", True),
            "affiliated": cfg_block.get("affiliated", False),
            "strapping":  cfg_block.get("strapping", 0),
            "parrot":     cfg_block.get("parrot", False),
            "inclusion": inclusion,
            "exclusion": exclusion,
            "always": always,
            "rid_permitted": rid_permitted,
        })
    return result


def _normalize_tg_key(tgid: Any, slot: Any) -> tuple[str, str]:
    return (str(tgid).strip(), str(slot).strip())


def _extract_loaded_tg_status(result: dict) -> tuple[dict[tuple[str, str], dict[str, bool]], str | None, bool]:
    """Build a lookup of loaded talkgroup state keyed by TGID and slot."""
    if not isinstance(result, dict) or not result:
        return {}, "Empty response", False

    if not result.get("success", True):
        return {}, result.get("error", "Unknown error"), False

    tgs = result.get("tgs")
    if not isinstance(tgs, list):
        return {}, "No talkgroup data returned", False

    status_map: dict[tuple[str, str], dict[str, bool]] = {}
    for tg in tgs:
        if not isinstance(tg, dict):
            continue

        source = tg.get("source", {})
        key = _normalize_tg_key(source.get("tgid", ""), source.get("slot", ""))
        config = tg.get("config", {}) if isinstance(tg.get("config"), dict) else {}
        status_map[key] = {
            "loaded": True,
            "active": bool(config.get("active", False)),
            "invalid": bool(tg.get("invalid", False)),
        }

    return status_map, None, True


def _parse_bool_flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_rid_entries(path: Path) -> list[dict[str, Any]]:
    """Extract radio ID entries from a RID ACL CSV file."""
    entries: list[dict[str, Any]] = []
    with path.open(newline="") as fh:
        for row in csv.reader(fh):
            if not row:
                continue

            first_col = row[0].strip() if row[0] is not None else ""
            if not first_col or first_col.startswith("#"):
                continue

            normalized = [col.strip() for col in row]
            while len(normalized) < 7:
                normalized.append("")

            allowed_kids = [kid for kid in normalized[6].split("|") if kid]
            entries.append({
                "rid": first_col,
                "enabled": _parse_bool_flag(normalized[1]) if len(normalized) > 1 else False,
                "alias": normalized[2],
                "ip_address": normalized[3],
                "can_request_keys": _parse_bool_flag(normalized[4]),
                "can_rekey": _parse_bool_flag(normalized[5]),
                "allowed_kids": allowed_kids,
                "allowed_kids_display": " | ".join(allowed_kids),
            })

    return entries


@router.get("/talkgroups/{system}", response_class=HTMLResponse)
async def list_talkgroups(request: Request, system: str):
    import yaml as _yaml
    cfg = _cfg(request)
    path = cfg.system_tgid_acl_file
    entries = []
    error = None
    loaded_error = None
    loaded_status_known = False

    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )

    loaded_status_map: dict[tuple[str, str], dict[str, bool]] = {}
    try:
        loaded_result = await asyncio.to_thread(api_client.call, "fne-tgidlist")
        loaded_status_map, loaded_error, loaded_status_known = _extract_loaded_tg_status(loaded_result)
    except Exception as exc:
        loaded_error = str(exc)

    if not path or not path.exists():
        error = f"Talkgroup file not found: {path}"
    else:
        try:
            data = _yaml.safe_load(path.read_text()) or {}
            entries = _extract_tg_entries(data)
            for entry in entries:
                key = _normalize_tg_key(entry.get("tgid", ""), entry.get("slot", ""))
                loaded_state = loaded_status_map.get(key, {})
                entry["loaded_status_known"] = loaded_status_known
                entry["loaded"] = bool(loaded_state.get("loaded", False))
                entry["loaded_active"] = bool(loaded_state.get("loaded", False)) and bool(loaded_state.get("active", False)) and not bool(loaded_state.get("invalid", False))
                entry["loaded_invalid"] = bool(loaded_state.get("invalid", False))
        except Exception as exc:
            error = str(exc)
    return _frag(request, "fragments/talkgroup_list.html", {
        "entries": entries,
        "system": system,
        "error": error,
        "loaded_error": loaded_error,
    })


@router.get("/radio-ids/{system}", response_class=HTMLResponse)
async def list_radio_ids(request: Request, system: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    path = cfg.system_rid_acl_file
    entries = []
    error = None
    if not path or not path.exists():
        error = f"Radio ID file not found: {path}"
    else:
        try:
            entries = _extract_rid_entries(path)
        except Exception as exc:
            error = str(exc)

    return _frag(request, "fragments/radio_id_list.html", {
        "entries": entries,
        "system": system,
        "error": error,
    })


@router.post("/radio-ids/{system}/reload")
async def reload_radio_ids(request: Request, system: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    mgr = RadioIDManager(cfg)
    target = "system" if system == "system" else "issi"
    try:
        result = await asyncio.to_thread(mgr.reload, target)
        success = all(r.get("success", True) for r in result.values())
        msg = f"{system.title()} radio IDs reloaded" if success else "Reload failed"
        return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))


@router.get("/talkgroups/{system}/yaml", response_class=HTMLResponse)
async def get_talkgroup_yaml(request: Request, system: str):
    cfg = _cfg(request)
    path = cfg.system_tgid_acl_file
    title = "Edit System Talkgroups"

    if not path or not path.exists():
        return Response(f"Talkgroup file not found: {path}", status_code=404)

    content = path.read_text()
    return _frag(request, "fragments/yaml_editor.html", {
        "name": system,
        "content": content,
        "save_url": f"/api/talkgroups/{system}/yaml",
        "title": title,
    })


@router.post("/talkgroups/{system}/yaml")
async def save_talkgroup_yaml(
    request: Request,
    system: str,
    yaml_content: Annotated[str, Form()],
):
    cfg = _cfg(request)
    path = cfg.system_tgid_acl_file
    if not path:
        return Response(status_code=200, headers=_toast("Talkgroup file path not configured", "error"))
    try:
        path.write_text(yaml_content)
        return Response(status_code=200, headers=_toast(f"{system.title()} talkgroups saved"))
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))


@router.post("/talkgroups/{system}/reload")
async def reload_talkgroups(request: Request, system: str):
    cfg = _cfg(request)
    mgr = TalkgroupManager(cfg)
    try:
        result = await asyncio.to_thread(mgr.reload, system)
        success = all(r.get("success", True) for r in result.values())
        msg = f"{system.title()} talkgroups reloaded" if success else "Reload failed"
        return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))


# ---------------------------------------------------------------------------
# Radio ID Commands
# ---------------------------------------------------------------------------

@router.post("/radio/{command}", response_class=HTMLResponse)
async def radio_command(
    request: Request,
    command: str,
):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    mgr = RadioIDManager(cfg)

    try:
        form = await request.form()
        rid_raw = form.get("rid")
        peer_id_raw = form.get("peer_id")
        rid = int(str(rid_raw).strip()) if rid_raw is not None and str(rid_raw).strip() else None
        peer_id_value = int(str(peer_id_raw).strip()) if peer_id_raw is not None and str(peer_id_raw).strip() else None
        if rid is None:
            raise ValueError("Radio ID is required")
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))

    cmd_map = {
        "inhibit": mgr.inhibit,
        "uninhibit": mgr.uninhibit,
        "check": mgr.check,
        "page": mgr.page,
    }

    fn = cmd_map.get(command)
    if fn is None:
        return Response(status_code=200, headers=_toast(f"Unknown command: {command}", "error"))

    result = await asyncio.to_thread(fn, rid, peer_id_value)
    success = result.get("success", True)
    msg = f"RID {rid}, {command.capitalize()} {'Sent' if success else 'Failed'}"
    if not success:
        msg = result.get("error", msg)
    return _frag(request, "fragments/result.html", {
        "success": success,
        "message": msg,
        "detail": result,
    })


# ---------------------------------------------------------------------------
# Service Management
# ---------------------------------------------------------------------------

@router.post("/services/reload-talkgroups/{system}")
async def reload_tg_service(request: Request, system: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    mgr = TalkgroupManager(cfg)
    try:
        result = await asyncio.to_thread(mgr.reload, system)
        success = all(r.get("success", True) for r in result.values())
        msg = f"Talkgroups ({system}) reloaded" if success else "Reload failed"
        return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))


@router.post("/services/reload-rids")
async def reload_rids(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )
    result = await asyncio.to_thread(api_client.reload_rids)
    success = result.get("success", True)
    msg = "Radio IDs reloaded" if success else result.get("error", "Reload failed")
    return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))


@router.post("/services/reload-peerlist")
async def reload_peerlist(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )
    result = await asyncio.to_thread(api_client.call, "fne-reload-peerid-acl")
    success = result.get("success", True)
    msg = "Peer list reloaded" if success else result.get("error", "Reload failed")
    return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))


@router.post("/services/reload-crypto")
async def reload_crypto(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )
    result = await asyncio.to_thread(api_client.call, "fne-reload-crypto")
    success = result.get("success", True)
    msg = "Crypto reloaded" if success else result.get("error", "Reload failed")
    return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))


@router.post("/services/force-update")
async def force_update(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    api_client = DVMAPIClient(
        host=cfg.api_host, port=cfg.system_port,
        password=cfg.system_acl,
    )
    result = await asyncio.to_thread(api_client.force_update)
    success = result.get("success", True)
    msg = "Force update sent to peers" if success else result.get("error", "Update failed")
    return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))


@router.get("/services/pids", response_class=HTMLResponse)
async def show_process_pids(request: Request):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    proc_mgr = ProcessManager()
    try:
        now = datetime.now().timestamp()
        services = await asyncio.to_thread(proc_mgr.get_all_services)
        service_rows = []
        for service_key in ProcessManager.SERVICES.keys():
            if service_key == "sysview" and not cfg.system_watch_enabled:
                continue

            info = services.get(service_key, {})
            count = int(info.get("count", 0) or 0)

            instances = []
            for instance in info.get("instances", []):
                started_at = ""
                elapsed = ""
                create_time = instance.get("create_time")
                if isinstance(create_time, (int, float)) and create_time > 0:
                    started_at = datetime.fromtimestamp(create_time).strftime("%Y-%m-%d %H:%M:%S")
                    elapsed_delta = timedelta(seconds=max(0, int(now - create_time)))
                    elapsed_days = elapsed_delta.days
                    elapsed_hours, remainder = divmod(elapsed_delta.seconds, 3600)
                    elapsed_minutes, elapsed_seconds = divmod(remainder, 60)
                    if elapsed_days > 0:
                        elapsed = f"{elapsed_days}d {elapsed_hours:02d}:{elapsed_minutes:02d}:{elapsed_seconds:02d}"
                    else:
                        elapsed = f"{elapsed_hours:02d}:{elapsed_minutes:02d}:{elapsed_seconds:02d}"

                updated_instance = dict(instance)
                updated_instance["started_at"] = started_at
                updated_instance["elapsed"] = elapsed
                instances.append(updated_instance)

            service_rows.append({
                "key": service_key,
                "name": info.get("name", service_key),
                "state": info.get("state", "unknown"),
                "count": count,
                "instances": instances,
                "pid": info.get("pid"),
            })
        return _frag(request, "fragments/pids_output.html", {
            "services": service_rows,
            "has_running": any(row["count"] for row in service_rows),
        })
    except Exception as exc:
        return _frag(request, "fragments/pids_output.html", {
            "services": [],
            "has_running": False,
            "error": str(exc),
        })


@router.post("/services/restart/{service}")
async def restart_service(request: Request, service: str):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    proc_mgr = ProcessManager()
    try:
        if service == "sysview" and not cfg.system_watch_enabled:
            return Response(status_code=200, headers=_toast("System Watch is disabled; sysview restart is unavailable", "error"))

        if not proc_mgr.is_service_supported(service):
            return Response(status_code=200, headers=_toast(f"Unknown service '{service}'", "error"))

        success = await asyncio.to_thread(proc_mgr.restart_service, service)
        msg = f"Service '{service}' restarted" if success else f"Failed to restart '{service}'"
        return Response(status_code=200, headers=_toast(msg, "success" if success else "error"))
    except Exception as exc:
        return Response(status_code=200, headers=_toast(str(exc), "error"))


@router.post("/console/run", response_class=HTMLResponse)
async def run_console_command(
    request: Request,
):
    form = await request.form()
    raw_command = str(form.get("command") or "").strip()
    if not raw_command:
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": "",
            "exit_code": 1,
            "output": "Command cannot be empty.",
        })

    if raw_command.lower() in {"exit", "quit", "tui", "talkgroup", "shell"}:
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": raw_command,
            "exit_code": 2,
            "output": f"Command blocked: '{raw_command}' is disabled in browser console.",
        })

    try:
        cmd_tokens = shlex.split(raw_command)
    except ValueError as exc:
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": raw_command,
            "exit_code": 2,
            "output": f"Failed to parse command: {exc}",
        })

    launch_cmd = [sys.executable, "-m", "run", "--mode", "cli"] + cmd_tokens
    run_cwd = str((Path(__file__).resolve().parents[3]))

    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            launch_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=run_cwd,
            env={**os.environ, "TERM": "xterm-256color", "COLUMNS": "140"},
        )
        merged = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
        clean_output = _ANSI_RE.sub("", merged).strip() or "(no output)"
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": raw_command,
            "exit_code": completed.returncode,
            "output": clean_output,
        })
    except subprocess.TimeoutExpired:
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": raw_command,
            "exit_code": 124,
            "output": "Command timed out after 30 seconds.",
        })
    except Exception as exc:
        return _frag(request, "fragments/console_output_entry.html", {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "command": raw_command,
            "exit_code": 1,
            "output": f"Execution error: {exc}",
        })


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@router.get("/logs/{log_type}", response_class=HTMLResponse)
async def get_log(
    request: Request,
    log_type: str,
    lines: int = 200,
    filter_pattern: Optional[str] = None,
):
    proxied = await _proxy_if_remote(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)
    try:
        log_lines = await asyncio.to_thread(_read_web_logs, cfg, log_type, lines, filter_pattern)
        rendered_lines = [_format_log_line_html(line) for line in log_lines]
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        rendered_lines = [_format_log_line_html(str(exc))]
    except Exception as exc:
        rendered_lines = [_format_log_line_html(f"Error reading log: {exc}")]
    return _frag(request, "fragments/log_output.html", {
        "log_lines": rendered_lines,
        "log_type": log_type,
    })

