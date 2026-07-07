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
"""Federation target selection, authentication, and proxy helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, MutableMapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from requests.exceptions import SSLError

from dvm_mgmt.core.config import ConsoleConfig, FederationNodeConfig

_HEADER_NODE = "x-dvmmgmt-fed-node"
_HEADER_TS = "x-dvmmgmt-fed-ts"
_HEADER_NONCE = "x-dvmmgmt-fed-nonce"
_HEADER_SIG = "x-dvmmgmt-fed-sig"


@dataclass(frozen=True)
class FederationTarget:
    """Resolved target metadata used by web handlers."""

    target_id: str
    name: str
    base_url: str
    log_prefix_system: Optional[str]
    is_local: bool
    enabled: bool = True


class FederationManager:
    """Shared federation orchestration for API/stream/websocket layers."""

    def __init__(self, config: ConsoleConfig) -> None:
        self._config = config
        self._enabled = bool(config.federation_enabled)
        self._shared_secret = str(config.federation_shared_secret or "").strip()
        self._secret_bytes = self._shared_secret.encode("utf-8")
        self._timeout = max(float(config.federation_timeout_sec or 5.0), 1.0)
        self._verify_tls = bool(config.federation_tls_verify)
        self._auth_window_sec = max(int(config.federation_auth_window_sec or 30), 10)

        local_name = "Local"
        self._local_target = FederationTarget(
            target_id="local",
            name=local_name,
            base_url="",
            log_prefix_system=str(config.log_prefix_system or "").strip() or None,
            is_local=True,
            enabled=True,
        )

        self._targets: Dict[str, FederationTarget] = {"local": self._local_target}
        for node in list(config.federation_nodes or []):
            if not isinstance(node, FederationNodeConfig):
                continue
            node_id = str(node.id or "").strip().lower()
            if not node_id or node_id == "local":
                continue
            base_url = str(node.url or "").strip().rstrip("/")
            if not base_url:
                continue
            name = str(node.name or node_id).strip() or node_id
            self._targets[node_id] = FederationTarget(
                target_id=node_id,
                name=name,
                base_url=base_url,
                log_prefix_system=str(node.log_prefix_system or "").strip() or None,
                is_local=False,
                enabled=bool(node.enabled),
            )

        self._nonce_lock = threading.Lock()
        self._nonce_cache: Dict[str, float] = {}
        self._node_info_lock = threading.Lock()
        self._node_info_cache: Dict[str, Dict[str, Any]] = {}
        self._node_info_ttl_sec = 300.0

    @property
    def enabled(self) -> bool:
        """Return whether federation features are operational for this node."""
        return self._enabled and bool(self._shared_secret)

    def targets(self) -> list[FederationTarget]:
        """Return local target followed by remote targets sorted by display name."""
        ordered = [self._local_target]
        remotes = [target for key, target in self._targets.items() if key != "local"]
        remotes.sort(key=lambda item: item.name.lower())
        ordered.extend(remotes)
        return ordered

    def default_target_id(self) -> str:
        """Return the default target identifier used for new sessions."""
        return "local"

    def resolve_target(self, target_id: Optional[str]) -> FederationTarget:
        """Resolve a target identifier and fall back to local when unknown."""
        normalized = str(target_id or "").strip().lower()
        if not normalized:
            return self._local_target
        return self._targets.get(normalized, self._local_target)

    def selected_target(self, session: Optional[Mapping[str, Any]]) -> FederationTarget:
        """Resolve the currently selected target from a session mapping."""
        session_target = None
        if isinstance(session, Mapping):
            session_target = session.get("federation_target")
        return self.resolve_target(str(session_target or "local"))

    def selected_target_from_request(self, request) -> FederationTarget:
        """Resolve the active target from session first, then cookie fallback."""
        session_target = None
        try:
            session_target = request.session.get("federation_target")
        except Exception:
            session_target = None

        if session_target:
            return self.resolve_target(str(session_target))

        cookie_target = None
        try:
            cookie_target = request.cookies.get("federation_target")
        except Exception:
            cookie_target = None

        if cookie_target:
            return self.resolve_target(str(cookie_target))

        return self._local_target

    def set_selected_target(self, session: MutableMapping[str, Any], target_id: str) -> FederationTarget:
        """Persist and return the resolved federation target for this session."""
        target = self.resolve_target(target_id)
        session["federation_target"] = target.target_id
        return target

    def system_prefix_for_target(self, target: FederationTarget, local_prefix: str) -> str:
        """Return the system log prefix for a target using cache/config fallbacks."""
        local_value = str(local_prefix or "").strip() or "N/A"
        if target.is_local:
            return local_value

        configured = str(target.log_prefix_system or "").strip()
        if configured:
            return configured

        now = time.time()
        with self._node_info_lock:
            cached = self._node_info_cache.get(target.target_id)
            if cached and float(cached.get("expires_at", 0)) > now:
                remote = str(cached.get("log_prefix_system") or "").strip()
                if remote:
                    return remote

        return "N/A"

    def hostname_for_target(self, target: FederationTarget, local_hostname: str) -> str:
        """Return a human-readable hostname for a target with cache fallbacks."""
        if target.is_local:
            return local_hostname

        now = time.time()
        with self._node_info_lock:
            cached = self._node_info_cache.get(target.target_id)
            if cached and float(cached.get("expires_at", 0)) > now:
                remote = str(cached.get("hostname") or "").strip()
                if remote:
                    return remote

        configured_name = str(target.name or "").strip()
        if configured_name:
            return configured_name

        parsed = urlsplit(target.base_url)
        return str(parsed.hostname or local_hostname).strip() or local_hostname

    def refresh_remote_node_info(self, target: FederationTarget, force: bool = False) -> Optional[str]:
        """Fetch and cache remote node identity metadata when federation is enabled."""
        if target.is_local or not self.enabled:
            return None

        now = time.time()
        with self._node_info_lock:
            cached = self._node_info_cache.get(target.target_id)
            if not force and cached and float(cached.get("expires_at", 0)) > now:
                return str(cached.get("log_prefix_system") or "").strip() or None

        try:
            upstream = self.proxy_request(
                target=target,
                method="GET",
                path="/api/federation/node-info",
                query_params=None,
                body=b"",
                content_type="",
                accept="application/json",
                stream=False,
            )
        except Exception:
            return None

        if upstream.status_code >= 400:
            return None

        try:
            payload = upstream.json()
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        prefix = str(payload.get("log_prefix_system") or "").strip()
        remote_hostname = str(payload.get("hostname") or "").strip()
        with self._node_info_lock:
            self._node_info_cache[target.target_id] = {
                "log_prefix_system": prefix,
                "hostname": remote_hostname,
                "expires_at": time.time() + self._node_info_ttl_sec,
            }
        return prefix or None

    def can_accept_federated_auth(self, path: str) -> bool:
        """Return whether the request path is eligible for federation auth."""
        if not self.enabled:
            return False
        if not path:
            return False
        return path.startswith("/api/") or path.startswith("/stream/") or path.startswith("/ws/")

    def build_auth_headers(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
    ) -> Dict[str, str]:
        """Build signed federation authentication headers for outbound requests."""
        if not self.enabled:
            return {}

        now = str(int(time.time()))
        nonce = secrets.token_hex(16)
        node_id = str(self._config.federation_node_id or "local").strip().lower() or "local"
        sig = self._sign(
            method=method,
            path=path,
            query=query,
            body=body,
            ts=now,
            nonce=nonce,
            node_id=node_id,
        )
        return {
            _HEADER_NODE: node_id,
            _HEADER_TS: now,
            _HEADER_NONCE: nonce,
            _HEADER_SIG: sig,
        }

    def verify_auth_headers(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> tuple[bool, str]:
        """Validate inbound federation auth headers and prevent replay attacks."""
        if not self.enabled:
            return False, "Federation auth disabled"
        if not self.can_accept_federated_auth(path):
            return False, "Path not allowed"

        node_id = str(headers.get(_HEADER_NODE, "")).strip().lower()
        ts_raw = str(headers.get(_HEADER_TS, "")).strip()
        nonce = str(headers.get(_HEADER_NONCE, "")).strip()
        recv_sig = str(headers.get(_HEADER_SIG, "")).strip()

        if not node_id or not ts_raw or not nonce or not recv_sig:
            return False, "Missing federation auth headers"

        try:
            ts = int(ts_raw)
        except Exception:
            return False, "Invalid timestamp"

        now = int(time.time())
        if abs(now - ts) > self._auth_window_sec:
            return False, "Federation auth timestamp expired"

        if not self._consume_nonce(nonce, now + self._auth_window_sec):
            return False, "Federation auth nonce replay detected"

        expected = self._sign(
            method=method,
            path=path,
            query=query,
            body=body,
            ts=ts_raw,
            nonce=nonce,
            node_id=node_id,
        )
        if not hmac.compare_digest(expected, recv_sig):
            return False, "Invalid federation signature"

        return True, node_id

    def proxy_request(
        self,
        target: FederationTarget,
        method: str,
        path: str,
        query_params: Optional[Mapping[str, Any]] = None,
        body: Optional[bytes] = None,
        content_type: str = "",
        accept: str = "",
        stream: bool = False,
    ) -> requests.Response:
        """Proxy an HTTP request to a remote federation target."""
        if target.is_local:
            raise ValueError("proxy_request called with local target")

        query = ""
        if query_params:
            query = urlencode([(k, v) for k, v in query_params.items() if v is not None], doseq=True)

        body_bytes = body or b""
        headers = {
            "accept": accept or "*/*",
        }
        if content_type:
            headers["content-type"] = content_type
        headers.update(self.build_auth_headers(method=method, path=path, query=query, body=body_bytes))

        url = self._build_target_url(target.base_url, path, query)
        try:
            return requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body_bytes if body_bytes else None,
                timeout=self._timeout,
                verify=self._verify_tls,
                stream=stream,
            )
        except SSLError:
            split = urlsplit(url)
            if split.scheme != "https":
                raise

            fallback_url = urlunsplit(("http", split.netloc, split.path, split.query, ""))
            return requests.request(
                method=method,
                url=fallback_url,
                headers=headers,
                data=body_bytes if body_bytes else None,
                timeout=self._timeout,
                verify=False,
                stream=stream,
            )

    @staticmethod
    def _build_target_url(base_url: str, path: str, query: str) -> str:
        """Compose an upstream URL from base URL, request path, and query string."""
        split = urlsplit(base_url)
        normalized_path = path if path.startswith("/") else f"/{path}"
        new_path = split.path.rstrip("/") + normalized_path
        return urlunsplit((split.scheme, split.netloc, new_path, query, ""))

    def _sign(
        self,
        method: str,
        path: str,
        query: str,
        body: bytes,
        ts: str,
        nonce: str,
        node_id: str,
    ) -> str:
        """Create an HMAC signature for federation request authentication."""
        body_hash = hashlib.sha256(body or b"").hexdigest()
        material = "\n".join([
            (method or "GET").upper(),
            path or "/",
            query or "",
            body_hash,
            ts,
            nonce,
            node_id,
        ])
        return hmac.new(self._secret_bytes, material.encode("utf-8"), hashlib.sha256).hexdigest()

    def _consume_nonce(self, nonce: str, expires_at: float) -> bool:
        """Record nonce usage and reject duplicates within the validity window."""
        now = time.time()
        with self._nonce_lock:
            stale = [key for key, expiry in self._nonce_cache.items() if expiry < now]
            for key in stale:
                self._nonce_cache.pop(key, None)

            if nonce in self._nonce_cache:
                return False

            self._nonce_cache[nonce] = expires_at
            return True

