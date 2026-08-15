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
DVM Management Web Interface - FastAPI Application
"""

import hashlib
import os
import socket
import contextlib
import asyncio
import codecs
import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit

import uvicorn
import websockets
from fastapi import Depends, FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse, StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dvm_mgmt.core.config import ConsoleConfig
from dvm_mgmt.web.federation import FederationManager
from dvm_mgmt.web.routes import api, stream
from dvm_mgmt.web.system_watch import SystemWatchBridge

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _session_secret(config: ConsoleConfig) -> str:
    """Resolve a stable session secret key."""
    env_secret = os.getenv("WEB_SESSION_SECRET", "").strip()
    if len(env_secret) >= 32:
        return env_secret

    # Deterministic fallback keeps sessions stable across restarts.
    material = f"{config.system_acl}|{config.api_host}|{config.system_port}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _safe_next(next_url: str) -> str:
    """Allow only local redirect targets."""
    if not next_url:
        return "/"
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def _normalize_root_path(raw_root: str) -> str:
    root = str(raw_root or "").strip()
    if not root:
        return ""
    if not root.startswith("/"):
        root = "/" + root
    root = root.rstrip("/")
    return "" if root == "/" else root


def _strip_root_prefix(path: str, root_path: str) -> str:
    if not root_path:
        return path or "/"
    if path == root_path:
        return "/"
    prefix = root_path + "/"
    if path.startswith(prefix):
        trimmed = path[len(root_path):]
        return trimmed if trimmed.startswith("/") else "/" + trimmed
    return path or "/"


def _with_root(path: str, root_path: str) -> str:
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    if not root_path:
        return path
    if path == root_path or path.startswith(root_path + "/"):
        return path
    return root_path + path


def _display_hostname(selected_target, local_hostname: str) -> str:
    if selected_target is None or getattr(selected_target, "is_local", True):
        return local_hostname

    base_url = str(getattr(selected_target, "base_url", "") or "").strip()
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.hostname:
            return parsed.hostname

    return str(getattr(selected_target, "name", "") or local_hostname).strip() or local_hostname


def _display_system_prefix(selected_target, local_prefix: str) -> str:
    local_value = str(local_prefix or "").strip() or "N/A"
    if selected_target is None or getattr(selected_target, "is_local", True):
        return local_value

    remote_value = str(getattr(selected_target, "log_prefix_system", "") or "").strip()
    return remote_value or "N/A"


def _pam_authenticate(username: str, password: str, pam_service: str) -> bool:
    """Authenticate a Linux user through PAM."""
    try:
        import pam  # type: ignore
        client = pam.pam()
        return bool(client.authenticate(username, password, service=pam_service))
    except ImportError:
        # Debian/Ubuntu often provide python3-pam as `PAM` (uppercase module name).
        try:
            import PAM  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError("PAM module unavailable. Install python-pam or python3-pam on this host.") from exc

        def _conv(_auth, query_list, _user_data=None):
            responses = []
            for _query, qtype in query_list:
                if qtype in (PAM.PAM_PROMPT_ECHO_ON, PAM.PAM_PROMPT_ECHO_OFF):
                    responses.append((password, 0))
                else:
                    responses.append(("", 0))
            return responses

        auth = PAM.pam()
        auth.start(pam_service)
        auth.set_item(PAM.PAM_USER, username)
        auth.set_item(PAM.PAM_CONV, _conv)
        try:
            auth.authenticate()
            auth.acct_mgmt()
            return True
        except PAM.error:
            return False


def create_app(config: ConsoleConfig) -> FastAPI:
    """Create and configure the FastAPI application."""
    configured_root_path = _normalize_root_path(os.getenv("WEB_ROOT_PATH", ""))
    app = FastAPI(
        title="DVM Management Web Interface",
        docs_url=None,
        redoc_url=None,
        root_path=configured_root_path,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    pam_service = os.getenv("WEB_PAM_SERVICE", "login").strip() or "login"
    secure_cookie = os.getenv("WEB_SECURE_COOKIE", "0").strip() in {"1", "true", "yes", "on"}

    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(config),
        session_cookie="dvmmgmt_session",
        max_age=12 * 60 * 60,
        same_site="lax",
        https_only=secure_cookie,
    )

    app.state.config = config
    app.state.templates = templates
    app.state.federation = FederationManager(config)
    app.state.system_watch = SystemWatchBridge(config) if config.system_watch_enabled else None
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    hostname = socket.gethostname()
    def _is_authenticated(request: Request) -> bool:
        try:
            return bool(request.session.get("auth_user"))
        except AssertionError:
            return False

    async def _federation_body_from_request(request: Request) -> bytes:
        cached = getattr(request.state, "federation_raw_body", None)
        if isinstance(cached, (bytes, bytearray)):
            return bytes(cached)

        body_bytes = await request.body()
        request.state.federation_raw_body = body_bytes
        return body_bytes

    def _federation_request_path(request: Request) -> str:
        root_path = _request_root(request)
        return _strip_root_prefix(request.url.path, root_path)

    async def _is_federated_server_request(request: Request) -> bool:
        fed: FederationManager = request.app.state.federation
        if not fed.enabled:
            return False
        body_bytes = await _federation_body_from_request(request)
        ok, _ = fed.verify_auth_headers(
            method=request.method,
            path=_federation_request_path(request),
            query=request.url.query,
            body=body_bytes,
            headers=request.headers,
        )
        if ok:
            request.state.federation_request = True
            return True
        return False

    def _proxy_headers_from_upstream(upstream_headers) -> dict:
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

    def _path_allows_mutation(path: str) -> bool:
        allowed_prefixes = (
            "/api/radio/",
            "/api/services/",
            "/api/config-files",
        )
        return path.startswith(allowed_prefixes)

    def _request_root(request: Request) -> str:
        from_scope = _normalize_root_path(str(request.scope.get("root_path") or ""))
        if from_scope:
            return from_scope

        forwarded_prefix = request.headers.get("x-forwarded-prefix")
        if forwarded_prefix:
            # Use the first value when multiple prefixes are present.
            return _normalize_root_path(forwarded_prefix.split(",", 1)[0].strip())

        script_name = request.headers.get("x-script-name")
        if script_name:
            return _normalize_root_path(script_name)

        return _normalize_root_path(configured_root_path)

    def _require_page_auth(request: Request) -> Optional[RedirectResponse]:
        if _is_authenticated(request):
            return None
        root_path = _request_root(request)
        next_path = _strip_root_prefix(request.url.path, root_path)
        next_url = quote(next_path, safe="/")
        login_url = _with_root(f"/login?next={next_url}", root_path)
        return RedirectResponse(url=login_url, status_code=303)

    async def _require_api_auth(request: Request) -> None:
        if _is_authenticated(request):
            return
        if await _is_federated_server_request(request):
            return
        raise HTTPException(
            status_code=401,
            headers={"HX-Redirect": _with_root("/login", _request_root(request))},
        )

    async def _federation_proxy_middleware(request: Request, call_next):
        fed: FederationManager = request.app.state.federation
        root_path = _request_root(request)
        path = _strip_root_prefix(request.url.path, root_path)
        method = request.method.upper()

        if fed.enabled and _is_authenticated(request):
            selected = fed.selected_target_from_request(request)
            if not selected.is_local:
                await asyncio.to_thread(fed.refresh_remote_node_info, selected)

        # Local form posts must bypass body buffering; otherwise downstream form parsing can hang.
        if path.startswith((
            "/api/federation/",
            "/api/status",
            "/api/affiliations",
        )) or path in {"/login", "/logout"}:
            return await call_next(request)

        body = b""

        if (
            fed.enabled
            and not bool(getattr(request.state, "federation_request", False))
            and (path.startswith("/api/") or path.startswith("/stream/"))
            and not path.startswith("/api/federation/")
            and not path.startswith("/api/system-watch/")
            and _is_authenticated(request)
        ):
            target = fed.selected_target_from_request(request)
            if not target.is_local:
                body = await request.body()
                request.state.federation_raw_body = body

                if method in {"POST", "PUT", "PATCH", "DELETE"} and not _path_allows_mutation(path):
                    return Response(
                        status_code=403,
                        headers={
                            "HX-Trigger": json.dumps(
                                {
                                    "showToast": {
                                        "message": "Action blocked for federated view",
                                        "type": "error",
                                    }
                                }
                            )
                        },
                    )

                query = dict(request.query_params.multi_items())
                accept = request.headers.get("accept", "*/*")
                content_type = request.headers.get("content-type", "")

                if path.startswith("/stream/"):
                    upstream = await asyncio.to_thread(
                        fed.proxy_request,
                        target,
                        method,
                        path,
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
                        headers=_proxy_headers_from_upstream(upstream.headers),
                        media_type=upstream.headers.get("content-type", "text/event-stream"),
                    )

                upstream = await asyncio.to_thread(
                    fed.proxy_request,
                    target,
                    method,
                    path,
                    query,
                    body,
                    content_type,
                    accept,
                    False,
                )
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    headers=_proxy_headers_from_upstream(upstream.headers),
                    media_type=upstream.headers.get("content-type"),
                )

        response = await call_next(request)
        return response

    app.middleware("http")(_federation_proxy_middleware)

    app.include_router(api.router, prefix="/api", dependencies=[Depends(_require_api_auth)])
    app.include_router(stream.router, prefix="/stream", dependencies=[Depends(_require_api_auth)])

    @app.on_event("startup")
    async def _startup_system_watch() -> None:
        relay: Optional[SystemWatchBridge] = app.state.system_watch
        if relay is not None:
            relay.start()

    @app.on_event("shutdown")
    async def _shutdown_system_watch() -> None:
        relay: Optional[SystemWatchBridge] = app.state.system_watch
        if relay is not None:
            await relay.stop()

    def _ctx(request: Request, page: str) -> dict:
        root_path = _request_root(request)
        fed: FederationManager = request.app.state.federation
        selected_target = fed.selected_target_from_request(request)
        display_hostname = fed.hostname_for_target(selected_target, hostname)
        display_system_prefix = fed.system_prefix_for_target(selected_target, config.log_prefix_system)
        return {
            "request": request,
            "config": config,
            "page": page,
            "hostname": display_hostname,
            "system_prefix": display_system_prefix,
            "auth_user": request.session.get("auth_user"),
            "root_path": root_path,
            "federation_configured": bool(config.federation_enabled),
            "federation_enabled": fed.enabled,
            "federation_targets": fed.targets(),
            "selected_target": selected_target,
        }

    @app.get("/api/federation/targets")
    async def federation_targets(request: Request):
        fed: FederationManager = request.app.state.federation
        selected = fed.selected_target_from_request(request)
        payload = {
            "enabled": fed.enabled,
            "selected": selected.target_id,
            "targets": [
                {
                    "id": target.target_id,
                    "name": target.name,
                    "is_local": target.is_local,
                }
                for target in fed.targets()
            ],
        }
        return JSONResponse(payload)

    @app.get("/api/federation/node-info")
    async def federation_node_info(request: Request):
        if not _is_authenticated(request):
            ok = await _is_federated_server_request(request)
            if not ok:
                raise HTTPException(status_code=401)

        return JSONResponse({
            "hostname": hostname,
            "log_prefix_system": str(config.log_prefix_system or "").strip(),
        })

    @app.post("/api/federation/select")
    async def federation_select(request: Request, target_id: str = Form("local"), next: str = Form("/")):
        if not _is_authenticated(request):
            raise HTTPException(status_code=401)
        fed: FederationManager = request.app.state.federation
        if not fed.enabled and target_id != "local":
            raise HTTPException(status_code=400, detail="Federation is disabled")
        target = fed.set_selected_target(request.session, target_id)
        if not target.enabled and not target.is_local:
            raise HTTPException(status_code=400, detail="Selected federation target is disabled")
        if not target.is_local:
            await asyncio.to_thread(fed.refresh_remote_node_info, target, True)
        root_path = _request_root(request)
        redirect_url = _safe_next(_strip_root_prefix(str(next).strip() or "/", root_path))
        response = RedirectResponse(url=_with_root(redirect_url, root_path), status_code=303)
        response.set_cookie(
            "dvmmgmt_federation_target",
            target.target_id,
            max_age=12 * 60 * 60,
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/configuration", response_class=HTMLResponse)
    async def configuration_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("configuration.html", _ctx(request, "configuration"))

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str = "/"):
        root_path = _request_root(request)
        safe_next = _safe_next(_strip_root_prefix(next, root_path))
        if request.session.get("auth_user"):
            return RedirectResponse(url=_with_root(safe_next, root_path), status_code=303)

        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "hostname": hostname,
                "error": "",
                "next": safe_next,
                "root_path": root_path,
            },
        )

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/"),
    ):
        clean_user = str(username).strip()
        root_path = _request_root(request)
        safe_next = _safe_next(_strip_root_prefix(str(next).strip() or "/", root_path))

        if not clean_user or not password:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "hostname": hostname,
                    "error": "Username and password are required",
                    "next": safe_next,
                    "root_path": root_path,
                },
                status_code=400,
            )

        try:
            ok = _pam_authenticate(clean_user, password, pam_service)
        except RuntimeError as exc:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "hostname": hostname,
                    "error": str(exc),
                    "next": safe_next,
                    "root_path": root_path,
                },
                status_code=500,
            )

        if not ok:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "hostname": hostname,
                    "error": "Invalid username or password",
                    "next": safe_next,
                    "root_path": root_path,
                },
                status_code=401,
            )

        request.session.clear()
        request.session["auth_user"] = clean_user
        return RedirectResponse(url=_with_root(safe_next, root_path), status_code=303)

    @app.get("/logout")
    @app.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url=_with_root("/login", _request_root(request)), status_code=303)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("dashboard.html", _ctx(request, "dashboard"))

    @app.get("/peers", response_class=HTMLResponse)
    async def peers_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("peers.html", _ctx(request, "peers"))

    @app.get("/connected-peers", response_class=HTMLResponse)
    async def connected_peers_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("connected_peers.html", _ctx(request, "connected-peers"))

    @app.get("/system-watch", response_class=HTMLResponse)
    async def system_watch_page(request: Request):
        if not config.system_watch_enabled:
            raise HTTPException(status_code=404, detail="System Watch is disabled")
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("system_watch.html", _ctx(request, "system-watch"))

    @app.get("/edit-peers", response_class=HTMLResponse)
    async def edit_peers_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("edit_peers.html", _ctx(request, "edit-peers"))

    @app.get("/talkgroups", response_class=HTMLResponse)
    async def talkgroups_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("talkgroups.html", _ctx(request, "talkgroups"))

    @app.get("/radio-ids", response_class=HTMLResponse)
    async def radio_ids_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("radio_ids.html", _ctx(request, "radio-ids"))

    @app.get("/radio", response_class=HTMLResponse)
    async def radio_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("radio.html", _ctx(request, "radio"))

    @app.get("/services", response_class=HTMLResponse)
    async def services_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("services.html", _ctx(request, "services"))

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("logs.html", _ctx(request, "logs"))

    @app.get("/console", response_class=HTMLResponse)
    async def console_page(request: Request):
        auth_redirect = _require_page_auth(request)
        if auth_redirect:
            return auth_redirect
        return templates.TemplateResponse("console.html", _ctx(request, "console"))

    @app.websocket("/ws/system-watch")
    async def system_watch_ws(websocket: WebSocket):
        relay: Optional[SystemWatchBridge] = websocket.app.state.system_watch
        if relay is None:
            await websocket.close(code=4404)
            return

        session = websocket.scope.get("session") or {}
        if not session.get("auth_user"):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        await relay.add_client(websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await relay.remove_client(websocket)

    @app.websocket("/ws/console")
    async def console_ws(websocket: WebSocket):
        session = websocket.scope.get("session") or {}
        fed: FederationManager = websocket.app.state.federation

        is_user_session = bool(session.get("auth_user"))
        if not is_user_session:
            headers = {
                key.lower(): value
                for key, value in websocket.headers.items()
            }
            ok, _ = fed.verify_auth_headers(
                method="GET",
                path=_strip_root_prefix(websocket.url.path, _request_root(websocket)),
                query=websocket.url.query,
                body=b"",
                headers=headers,
            )
            if not ok:
                await websocket.close(code=4401)
                return

        await websocket.accept()

        if is_user_session:
            selected = fed.selected_target(session)
            if not selected.is_local and fed.enabled:
                remote_ws_url = selected.base_url.replace("https://", "wss://").replace("http://", "ws://")
                remote_ws_url = f"{remote_ws_url}/ws/console"
                auth_headers = fed.build_auth_headers(
                    method="GET",
                    path="/ws/console",
                    query="",
                    body=b"",
                )
                try:
                    async with websockets.connect(
                        remote_ws_url,
                        extra_headers=auth_headers,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                    ) as remote:
                        async def _browser_to_remote() -> None:
                            while True:
                                data = await websocket.receive_text()
                                await remote.send(data)

                        async def _remote_to_browser() -> None:
                            async for message in remote:
                                if isinstance(message, bytes):
                                    message = message.decode("utf-8", errors="ignore")
                                await websocket.send_text(str(message))

                        await asyncio.gather(_browser_to_remote(), _remote_to_browser())
                        return
                except Exception as exc:
                    await websocket.send_text(f"[federation error] {exc}\n")
                    await websocket.close(code=1011)
                    return

        run_cwd = str((Path(__file__).resolve().parents[2]))
        env = {**os.environ, "TERM": "xterm-256color", "COLUMNS": "140"}
        proc = await asyncio.create_subprocess_exec(
            os.environ.get("PYTHON", "python3"),
            "-u",
            "-m",
            "run",
            "--mode",
            "cli",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=run_cwd,
            env=env,
        )

        async def _pump_output():
            if proc.stdout is None:
                return
            decoder = codecs.getincrementaldecoder("utf-8")()
            while True:
                chunk = await proc.stdout.read(1024)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    await websocket.send_text(text)

            tail = decoder.decode(b"", final=True)
            if tail:
                await websocket.send_text(tail)

        output_task = asyncio.create_task(_pump_output())
        blocked_cmds = {"exit", "quit"}

        try:
            while True:
                data = await websocket.receive_text()
                command = (data or "").strip().lower()
                if command in blocked_cmds:
                    await websocket.send_text("Command blocked: 'exit' and 'quit' are disabled in browser console.\n")
                    continue
                if proc.stdin is None or proc.returncode is not None:
                    break
                proc.stdin.write((data + "\n").encode("utf-8", errors="ignore"))
                await proc.stdin.drain()
        except WebSocketDisconnect:
            pass
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

            output_task.cancel()
            with contextlib.suppress(Exception):
                await output_task

    return app


def main(
    config_file: Optional[Path] = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> int:
    """Start the DVM Management web interface."""
    config = ConsoleConfig.load(config_file)
    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0
