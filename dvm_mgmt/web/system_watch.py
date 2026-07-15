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
"""SysView websocket relay used by the browser System Watch page."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Optional

import websockets
from fastapi import WebSocket

from dvm_mgmt.core.config import ConsoleConfig

STATE_DMR = 1
STATE_P25 = 2
STATE_NXDN = 3


def _safe_bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_control_capable(payload: dict[str, Any]) -> bool:
    return any(
        _safe_bool(payload.get(flag))
        for flag in ("dmrTSCCEnable", "p25CtrlEnable", "nxdnCtrlEnable")
    )


def _mode_for_control_peer(payload: dict[str, Any]) -> int:
    if _safe_bool(payload.get("nxdnCtrlEnable")):
        return STATE_NXDN
    if _safe_bool(payload.get("p25CtrlEnable")):
        return STATE_P25
    return STATE_DMR


def _normalize_virtual_channel_payload(
    parent_payload: dict[str, Any],
    vc_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(vc_payload)
    normalized["state"] = _mode_for_control_peer(parent_payload)
    normalized["vControl"] = True
    normalized["dmrTSCCEnable"] = False
    normalized["dmrCC"] = False
    normalized["p25CtrlEnable"] = False
    normalized["p25CC"] = False
    normalized["nxdnCtrlEnable"] = False
    normalized["nxdnCC"] = False
    return normalized


def _tile_entry(peer_id: int, unique_id: int, payload: dict[str, Any], last_seen: float) -> dict[str, Any]:
    return {
        "tileKey": f"{peer_id}:{unique_id}",
        "peerId": peer_id,
        "uniqueId": unique_id,
        "payload": payload,
        "lastSeen": last_seen,
    }


def _normalize_peer_tiles(peer_id: int, payload: dict[str, Any], last_seen: float) -> list[dict[str, Any]]:
    primary_channel_id = _safe_int(payload.get("channelId"))
    primary_channel_no = _safe_int(payload.get("channelNo"))

    tiles = [_tile_entry(peer_id, peer_id, dict(payload), last_seen)]
    vc_channels = payload.get("vcChannels")
    if not (_is_control_capable(payload) and isinstance(vc_channels, list)):
        return tiles

    sorted_channels = sorted(
        [entry for entry in vc_channels if isinstance(entry, dict)],
        key=lambda entry: (_safe_int(entry.get("channelId")), _safe_int(entry.get("channelNo"))),
    )

    for index, vc_payload in enumerate(sorted_channels):
        vc_channel_id = _safe_int(vc_payload.get("channelId"))
        vc_channel_no = _safe_int(vc_payload.get("channelNo"))

        # Match sysview: skip a vc entry when it duplicates the primary channel.
        if vc_channel_id == primary_channel_id and vc_channel_no == primary_channel_no:
            continue

        tiles.append(
            _tile_entry(
                peer_id,
                index,
                _normalize_virtual_channel_payload(payload, vc_payload),
                last_seen,
            )
        )

    return tiles


class SystemWatchBridge:
    """Maintain one sysview websocket connection and fan out peer status updates."""

    def __init__(self, config: ConsoleConfig) -> None:
        self._config = config
        self._clients: set[WebSocket] = set()
        self._latest_tiles: dict[str, dict[str, Any]] = {}
        self._peer_tile_keys: dict[int, set[str]] = {}
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background relay task if a sysview URL is configured."""
        if not self.url:
            return
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the relay task and detach all browser subscribers."""
        self._stop_event.set()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._task = None
        async with self._lock:
            self._clients.clear()

    @property
    def url(self) -> str:
        return str(getattr(self._config, "sysview_websocket_url", "") or "").strip()

    @property
    def connection_state(self) -> str:
        task = self._task
        if not self.url:
            return "disabled"
        if task is None:
            return "idle"
        if task.done():
            return "stopped"
        return "running"

    async def add_client(self, websocket: WebSocket) -> None:
        """Register a browser websocket and send the current snapshot."""
        async with self._lock:
            self._clients.add(websocket)
        self.start()
        await websocket.send_text(json.dumps(self.snapshot_message(), separators=(",", ":")))

    async def remove_client(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    def snapshot_message(self) -> dict[str, Any]:
        tiles = sorted(
            self._latest_tiles.values(),
            key=lambda item: (
                int(item.get("peerId") or 0),
                int(item.get("uniqueId") or 0),
                str(item.get("tileKey") or ""),
            ),
        )
        return {
            "type": "system_watch_snapshot",
            "source": "sysview",
            "url": self.url,
            "count": len(tiles),
            "tiles": tiles,
            "generatedAt": time.time(),
        }

    def _replace_peer_tiles(self, peer_id: int, payload: dict[str, Any], last_seen: float) -> dict[str, Any]:
        new_tiles = _normalize_peer_tiles(peer_id, payload, last_seen)
        old_keys = self._peer_tile_keys.get(peer_id, set())

        for tile_key in old_keys:
            self._latest_tiles.pop(tile_key, None)

        new_keys: set[str] = set()
        for tile in new_tiles:
            tile_key = str(tile.get("tileKey") or "")
            if not tile_key:
                continue
            self._latest_tiles[tile_key] = tile
            new_keys.add(tile_key)

        self._peer_tile_keys[peer_id] = new_keys
        return {
            "type": "system_watch_peer_tiles",
            "peerId": peer_id,
            "removedKeys": sorted(old_keys - new_keys),
            "tiles": new_tiles,
            "lastSeen": last_seen,
        }

    async def _broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, separators=(",", ":"), default=str)
        async with self._lock:
            clients = list(self._clients)

        stale: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_text(payload)
            except Exception:
                stale.append(client)

        if stale:
            async with self._lock:
                for client in stale:
                    self._clients.discard(client)

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            url = self.url
            if not url:
                return

            try:
                await self._broadcast({
                    "type": "system_watch_state",
                    "state": "connecting",
                    "url": url,
                })

                async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    backoff = 1.0
                    await self._broadcast({
                        "type": "system_watch_state",
                        "state": "connected",
                        "url": url,
                    })

                    async for raw_message in ws:
                        if self._stop_event.is_set():
                            break

                        if isinstance(raw_message, bytes):
                            raw_message = raw_message.decode("utf-8", errors="ignore")

                        try:
                            message = json.loads(raw_message)
                        except Exception:
                            continue

                        if not isinstance(message, dict):
                            continue

                        message_type = str(message.get("type") or "")

                        if message_type == "peer_status":
                            peer_id = int(message.get("peerId") or 0)
                            payload = message.get("payload")
                            if not isinstance(payload, dict):
                                payload = {}

                            last_seen = time.time()
                            normalized = self._replace_peer_tiles(peer_id, payload, last_seen)
                            await self._broadcast(normalized)
                        else:
                            await self._broadcast(message)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                await self._broadcast({
                    "type": "system_watch_state",
                    "state": "disconnected",
                    "url": url,
                    "error": str(exc),
                })
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    backoff = min(backoff * 2.0, 15.0)
