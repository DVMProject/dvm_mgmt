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
DVM Management Web Interface - SSE Streaming Routes
"""

import asyncio
import glob
import time
from collections import deque
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

import aiofiles
from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from dvm_mgmt.core.config import ConsoleConfig
from dvm_mgmt.web.federation import FederationManager

router = APIRouter()


def _encode_sse(message: Mapping[str, Any]) -> str:
    """Encode a single SSE message from a mapping payload."""
    lines = []

    event = message.get("event")
    if event:
        lines.append(f"event: {event}")

    event_id = message.get("id")
    if event_id is not None:
        lines.append(f"id: {event_id}")

    retry = message.get("retry")
    if retry is not None:
        lines.append(f"retry: {retry}")

    data = message.get("data", "")
    for line in str(data).splitlines() or [""]:
        lines.append(f"data: {line}")

    return "\n".join(lines) + "\n\n"


def _event_source_response(generator: AsyncIterator[Mapping[str, Any]]) -> StreamingResponse:
    """Return a standard SSE streaming response without external dependencies."""

    async def _stream() -> AsyncIterator[str]:
        async for message in generator:
            yield _encode_sse(message)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _cfg(request: Request) -> ConsoleConfig:
    return request.app.state.config


def _fed(request: Request) -> FederationManager:
    return request.app.state.federation


def _selected_target(request: Request):
    return _fed(request).selected_target_from_request(request)


def _proxied_request_path(request: Request) -> str:
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
    copied = {}
    allowed = {
        "content-type",
        "cache-control",
        "connection",
        "x-accel-buffering",
    }
    for key, value in upstream_headers.items():
        if key.lower() in allowed:
            copied[key] = value
    return copied


async def _proxy_if_remote_stream(request: Request):
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
        True,
    )

    def _iter_stream():
        try:
            for chunk in upstream.iter_content(chunk_size=1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        _iter_stream(),
        status_code=upstream.status_code,
        headers=_proxy_headers(upstream.headers),
        media_type=upstream.headers.get("content-type", "text/event-stream"),
    )


def _resolve_log_source(cfg: ConsoleConfig, log_type: str) -> tuple[Path, str]:
    normalized = log_type.replace("-", "_")

    if normalized != "system":
        raise ValueError(f"Unknown log type: {log_type}")
    return Path(cfg.log_file), normalized


def _line_matches_prefix(line: str, mode: str, cfg: ConsoleConfig) -> bool:
    if mode == "system":
        return cfg.log_prefix_system in line
    return mode == "system" and cfg.log_prefix_system in line


def _tail_filtered_lines(path: Path, limit: int, matches, max_bytes: int = 4 * 1024 * 1024) -> list[str]:
    if limit <= 0:
        return []
    if not path.exists():
        return []

    kept: deque[str] = deque(maxlen=limit)
    chunk_size = 64 * 1024

    with path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
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
                kept.appendleft(line)
                if len(kept) >= limit:
                    return list(kept)

    return list(kept)


@router.get("/logs/{log_type}")
async def stream_logs(request: Request, log_type: str):
    """SSE endpoint that streams a live log tail."""
    proxied = await _proxy_if_remote_stream(request)
    if proxied is not None:
        return proxied

    cfg = _cfg(request)

    try:
        log_path, mode = _resolve_log_source(cfg, log_type)
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        async def _error():
            yield {"data": f"ERROR: {exc}"}
        return _event_source_response(_error())

    async def event_generator():
        # Send the last 100 lines as the initial batch
        if log_path.exists():
            try:
                initial = await asyncio.to_thread(
                    _tail_filtered_lines,
                    log_path,
                    100,
                    lambda line: _line_matches_prefix(line, mode, cfg),
                )
                for line in initial:
                    yield {"data": line}
            except Exception:
                pass

        # Tail the file
        if not log_path.exists():
            yield {"data": f"Log file not found: {log_path}"}
            return

        async with aiofiles.open(log_path, "r") as f:
            # Seek to end
            await f.seek(0, 2)
            last_heartbeat = time.monotonic()

            while True:
                if await request.is_disconnected():
                    break

                line = await f.readline()
                if line:
                    clean = line.rstrip()
                    if _line_matches_prefix(clean, mode, cfg):
                        yield {"data": clean}
                    last_heartbeat = time.monotonic()
                else:
                    # Heartbeat prevents intermediate proxies/clients from appearing hung.
                    if time.monotonic() - last_heartbeat > 10:
                        yield {"event": "heartbeat", "data": "ping"}
                        last_heartbeat = time.monotonic()
                    await asyncio.sleep(0.5)

    return _event_source_response(event_generator())


@router.get("/status")
async def stream_status(request: Request):
    """SSE endpoint that pushes status updates every 15 seconds."""
    proxied = await _proxy_if_remote_stream(request)
    if proxied is not None:
        return proxied

    import socket
    import json
    from dvm_mgmt.core.process_manager import ProcessManager
    from dvm_mgmt.core.api_client import DVMAPIClient

    cfg = _cfg(request)
    templates = request.app.state.templates

    async def event_generator():
        proc_mgr = ProcessManager()
        api_client = DVMAPIClient(
            host=cfg.api_host, port=cfg.system_port,
            password=cfg.system_acl,
        )

        while True:
            if await request.is_disconnected():
                break

            try:
                services = await asyncio.to_thread(proc_mgr.get_all_services)
                stats_raw = await asyncio.to_thread(api_client.get_stats)
                stats = stats_raw if stats_raw.get("success", True) else {}

                try:
                    span_raw = await asyncio.to_thread(api_client.call, "fne-spanning-tree")
                    spanning_tree = (
                        span_raw.get("masterTree", [])
                        if span_raw.get("success", True)
                        else []
                    )
                except Exception:
                    spanning_tree = []

                html = templates.get_template("fragments/status.html").render({
                    "services": services,
                    "stats": stats,
                    "spanning_tree": spanning_tree,
                    "system_watch_enabled": cfg.system_watch_enabled,
                    "request": request,
                })
                yield {"data": html}

            except Exception as exc:
                yield {"data": f"<p class='text-red-400'>Error: {exc}</p>"}

            await asyncio.sleep(15)

    return _event_source_response(event_generator())


@router.get("/affiliations")
async def stream_affiliations(request: Request):
    """SSE endpoint that pushes affiliation updates every 30 seconds."""
    cfg = _cfg(request)
    templates = request.app.state.templates

    # Build name lookup tables once per connection (best-effort)
    rid_names: dict = {}
    tg_names: dict = {}
    try:
        import csv as _csv
        rid_path = cfg.system_rid_acl_file
        if rid_path and rid_path.exists():
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

    async def event_generator():
        from dvm_mgmt.core.api_client import DVMAPIClient
        api_client = DVMAPIClient(
            host=cfg.api_host, port=cfg.system_port,
            password=cfg.system_acl,
        )

        while True:
            if await request.is_disconnected():
                break

            try:
                result = await asyncio.to_thread(api_client.call, "fne-affs")
                affiliations = (
                    result.get("affiliations", [])
                    if result.get("success", True)
                    else []
                )
                html = templates.get_template("fragments/affiliations.html").render({
                    "affiliations": affiliations,
                    "rid_names": rid_names,
                    "tg_names": tg_names,
                    "request": request,
                })
                yield {"data": html}
            except Exception as exc:
                yield {"data": f"<p class='text-red-400'>Error: {exc}</p>"}

            await asyncio.sleep(30)

    return _event_source_response(event_generator())

