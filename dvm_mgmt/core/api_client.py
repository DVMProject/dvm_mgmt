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
REST API Client for DVM Services
"""

import hashlib
import json
import time
from dataclasses import dataclass
from requests import Response
import requests
from typing import Any, Dict, Optional, Tuple, Callable
from pathlib import Path


@dataclass(frozen=True)
class RequestSpec:
    """REST request details for a CLI-style command mapping."""

    method: str
    endpoint: str
    payload: Optional[Dict[str, Any]] = None


class DVMAPIClient:
    """Client for interacting with DVM REST API directly over HTTP(S)."""

    _SIMPLE_COMMANDS: Dict[str, Tuple[str, str]] = {
        "version": ("GET", "/version"),
        "status": ("GET", "/status"),
        "voice-ch": ("GET", "/voice-ch"),
        "fne-peerlist": ("GET", "/peer/query"),
        "fne-peer-query": ("GET", "/peer/query"),
        "fne-peercount": ("GET", "/peer/count"),
        "fne-tgidlist": ("GET", "/tg/query"),
        "fne-force-update": ("GET", "/force-update"),
        "fne-unitregs": ("GET", "/report-unit-regs"),
        "fne-affs": ("GET", "/report-affiliations"),
        "fne-grants": ("GET", "/report-grants"),
        "fne-reload-tgs": ("GET", "/reload-tgs"),
        "fne-reload-rids": ("GET", "/reload-rids"),
        "fne-reload-peerlist": ("GET", "/reload-peers"),
        "fne-reload-peerid-acl": ("GET", "/reload-peers"),
        "fne-reload-peers": ("GET", "/reload-peers"),
        "fne-reload-crypto": ("GET", "/reload-crypto"),
        "fne-rid-commit": ("GET", "/rid/commit"),
        "fne-tgid-commit": ("GET", "/tg/commit"),
        "fne-peer-commit": ("GET", "/peer/commit"),
        "fne-stats": ("GET", "/stats"),
        "fne-reset-total-calls": ("GET", "/stat-reset-total-calls"),
        "fne-reset-active-calls": ("GET", "/stat-reset-active-calls"),
        "fne-reset-call-collisions": ("GET", "/stat-reset-call-collisions"),
        "fne-spanning-tree": ("GET", "/spanning-tree"),
    }

    _P25_RID_COMMANDS: Dict[str, str] = {
        "p25-rid-page": "page",
        "p25-rid-check": "check",
        "p25-rid-inhibit": "inhibit",
        "p25-rid-uninhibit": "uninhibit",
        "p25-rid-dyn-regrp": "dyn-regrp",
        "p25-rid-dyn-regrp-cancel": "dyn-regrp-cancel",
        "p25-rid-dyn-regrp-lock": "dyn-regrp-lock",
        "p25-rid-dyn-regrp-unlock": "dyn-regrp-unlock",
        "p25-rid-gaq": "group-aff-req",
        "p25-rid-ureg": "unit-reg",
        "fne-p25-rid-page": "page",
        "fne-p25-rid-check": "check",
        "fne-p25-rid-inhibit": "inhibit",
        "fne-p25-rid-uninhibit": "uninhibit",
        "fne-p25-rid-dyn-regrp": "dyn-regrp",
        "fne-p25-rid-dyn-regrp-cancel": "dyn-regrp-cancel",
        "fne-p25-rid-dyn-regrp-lock": "dyn-regrp-lock",
        "fne-p25-rid-dyn-regrp-unlock": "dyn-regrp-unlock",
        "fne-p25-rid-gaq": "group-aff-req",
        "fne-p25-rid-ureg": "unit-reg",
    }

    _DMR_RID_COMMANDS: Dict[str, str] = {
        "dmr-rid-page": "page",
        "dmr-rid-check": "check",
        "dmr-rid-inhibit": "inhibit",
        "dmr-rid-uninhibit": "uninhibit",
        "fne-dmr-rid-page": "page",
        "fne-dmr-rid-check": "check",
        "fne-dmr-rid-inhibit": "inhibit",
        "fne-dmr-rid-uninhibit": "uninhibit",
    }
    
    # Commands that should be retried if they return empty results
    _RETRY_ON_EMPTY_COMMANDS: set = {
        "fne-affs",
        "fne-stats", 
        "fne-spanning-tree",
    }
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9290,
        password: str = "RPT1234",
        debug: bool = False,
        use_ssl: bool = False,
        timeout: float = 5.0,
        verify_ssl: bool = False,
        max_retries: int = 1,
        retry_delay: float = 0.5,
    ):
        """
        Initialize DVM API client.
        
        Args:
            host: API host address
            port: API port number
            password: API password
            debug: Enable debug output
            use_ssl: Use HTTPS transport
            timeout: HTTP timeout in seconds
            verify_ssl: Validate server TLS certificate
            max_retries: Maximum number of retries for queries that return empty results (default: 1, meaning up to 2 attempts total)
            retry_delay: Delay in seconds between retry attempts (default: 0.5)
        """
        self.host = host
        self.port = port
        self.password = password
        self.debug = debug
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    def call(self, command: str, *args: Any) -> Dict[str, Any]:
        """
        Execute a dvmcmd-compatible command against the REST API.
        
        Automatically retries certain commands (affiliations, stats, spanning tree) if they 
        return empty results.
        
        Args:
            command: Command to execute
            *args: Additional command arguments
        
        Returns:
            Dictionary with command result
        
        Raises:
            RuntimeError: If command fails
        """
        command_stripped = command.strip()
        
        # Determine if this command should be retried on empty results
        should_retry = command_stripped in self._RETRY_ON_EMPTY_COMMANDS
        
        # Make the initial attempt and retry attempts
        for attempt in range(1 + self.max_retries):
            result = self._execute_call(command_stripped, args)
            
            if self.debug and attempt > 0:
                print(f"[API DEBUG] Attempt {attempt + 1}/{1 + self.max_retries} for {command_stripped}")
            
            # Check if we should retry: command failed to execute OR empty data on a retryable command
            should_retry_now = (
                should_retry and 
                result.get('success', True) and
                self._is_result_empty(command_stripped, result)
            )
            
            if not should_retry_now or attempt >= self.max_retries:
                return result
            
            # Wait before retrying
            if self.debug:
                print(f"[API DEBUG] Empty result for {command_stripped}, retrying in {self.retry_delay}s...")
            time.sleep(self.retry_delay)
        
        return result

    def _is_result_empty(self, command: str, result: Dict[str, Any]) -> bool:
        """Check if the result is effectively empty for a given command."""
        if command == "fne-affs":
            return not result.get("affiliations", [])
        elif command == "fne-stats":
            return not result.get("peerStats", [])
        elif command == "fne-spanning-tree":
            return not result.get("masterTree", [])
        return False

    def _execute_call(self, command: str, args: Tuple[Any, ...]) -> Dict[str, Any]:
        """Execute a single call without retry logic."""
        try:
            spec = self._build_request_spec(command, args)
            token = self._authenticate()
            response = self._request(spec.method, spec.endpoint, token, spec.payload)

            parsed = self._parse_response(response)
            normalized = self._normalize_response(parsed)

            if isinstance(normalized, dict):
                normalized.setdefault('command', command)
                return normalized

            return {
                'success': True,
                'output': normalized,
                'command': command,
            }
        except ValueError as e:
            return {
                'success': False,
                'error': str(e),
                'returncode': -1,
                'command': command,
            }
        except requests.RequestException as e:
            http_code = e.response.status_code if getattr(e, 'response', None) is not None else -1
            detail = ''
            if getattr(e, 'response', None) is not None:
                detail = e.response.text.strip()
            error_message = str(e)
            if detail:
                error_message = f"{error_message}: {detail}"

            return {
                'success': False,
                'error': error_message,
                'returncode': http_code,
                'command': command,
                'host': self.host,
                'port': self.port,
            }
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to execute command {command}: {str(e)}",
                'returncode': -1,
                'command': command
            }

    def _build_base_url(self) -> str:
        """Build the scheme-qualified base URL for API calls."""
        scheme = 'https' if self.use_ssl else 'http'
        return f"{scheme}://{self.host}:{self.port}"

    @staticmethod
    def _normalize_response(response_data: Any) -> Any:
        """Ensure command responses include a normalized boolean success flag."""
        if not isinstance(response_data, dict):
            return response_data

        if 'success' in response_data:
            return response_data

        status = response_data.get('status')
        if status is None:
            response_data['success'] = True
            return response_data

        if isinstance(status, int):
            response_data['success'] = status in (0, 200)
            return response_data

        if isinstance(status, str):
            response_data['success'] = status.lower() in ('ok', 'success', '0', '200')
            return response_data

        response_data['success'] = True
        return response_data

    @staticmethod
    def _parse_response(response: Response) -> Any:
        """Parse HTTP response payloads with JSON-first fallback behavior."""
        content_type = response.headers.get('Content-Type', '')
        body = response.text or ''

        if 'application/json' in content_type.lower():
            return response.json()

        stripped = body.strip()
        if stripped.startswith('{') or stripped.startswith('['):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

        return {
            'success': response.ok,
            'status': response.status_code,
            'output': body,
        }

    def _authenticate(self) -> str:
        """Authenticate with the API and return an auth token string."""
        auth_hash = hashlib.sha256(self.password.encode('utf-8')).hexdigest()
        response = self._request('PUT', '/auth', None, {'auth': auth_hash})
        parsed = self._parse_response(response)

        if not isinstance(parsed, dict):
            raise RuntimeError('Authentication response was not a JSON object')

        status = parsed.get('status')
        status_text = str(status).lower() if status is not None else ''
        if status not in (0, 200) and status_text not in ('0', '200', 'ok', 'success'):
            error_text = parsed.get('message') or parsed.get('error') or 'Invalid authentication response'
            raise RuntimeError(str(error_text))

        token = parsed.get('token')
        if not token:
            raise RuntimeError('Authentication token missing from response')

        return str(token)

    def _request(
        self,
        method: str,
        endpoint: str,
        token: Optional[str],
        payload: Optional[Dict[str, Any]],
    ) -> Response:
        """Issue a single HTTP request to the DVM API."""
        url = f"{self._build_base_url()}{endpoint}"
        headers = {'Accept': 'application/json'}

        if token:
            headers['X-DVM-Auth-Token'] = token

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        return response

    def _build_request_spec(self, command: str, args: Tuple[Any, ...]) -> RequestSpec:
        """Map a CLI-style command and args to an HTTP request specification."""
        if command in self._SIMPLE_COMMANDS:
            method, endpoint = self._SIMPLE_COMMANDS[command]
            return RequestSpec(method=method, endpoint=endpoint)

        if command == 'fne-reset-peer':
            if not args or args[0] is None:
                raise ValueError('fne-reset-peer requires <peerId>')
            return RequestSpec(
                method='PUT',
                endpoint='/peer/reset',
                payload={'peerId': int(args[0])},
            )

        if command in ('fne-peer-acl-add', 'fne-peer-acl-del'):
            if not args or args[0] is None:
                raise ValueError(f'{command} requires <peerId>')
            endpoint = '/peer/add' if command == 'fne-peer-acl-add' else '/peer/delete'
            return RequestSpec(method='PUT', endpoint=endpoint, payload={'peerId': int(args[0])})

        if command == 'fne-peer-reset-conn':
            if not args or args[0] is None:
                raise ValueError('fne-peer-reset-conn requires <peerId>')
            return RequestSpec(
                method='PUT',
                endpoint='/peer/connreset',
                payload={'peerId': int(args[0])},
            )

        if command == 'fne-peer-nak':
            if len(args) < 3 or args[0] is None or args[1] is None or args[2] is None:
                raise ValueError('fne-peer-nak requires <peerId> <tag> <reason>')
            return RequestSpec(
                method='PUT',
                endpoint='/peer/nak/byPeerId',
                payload={
                    'peerId': int(args[0]),
                    'tag': str(args[1]),
                    'reason': int(args[2]),
                },
            )

        if command == 'fne-peer-nak-addr':
            if len(args) < 5:
                raise ValueError('fne-peer-nak-addr requires <peerId> <tag> <reason> <address> <port>')
            if args[0] is None or args[1] is None or args[2] is None or args[3] is None or args[4] is None:
                raise ValueError('fne-peer-nak-addr requires <peerId> <tag> <reason> <address> <port>')
            return RequestSpec(
                method='PUT',
                endpoint='/peer/nak/byAddress',
                payload={
                    'peerId': int(args[0]),
                    'tag': str(args[1]),
                    'reason': int(args[2]),
                    'address': str(args[3]),
                    'port': int(args[4]),
                },
            )

        if command in self._DMR_RID_COMMANDS:
            if len(args) < 2 or args[0] is None or args[1] is None:
                raise ValueError(f'{command} requires <slot> <rid> [peerId]')

            payload = {
                'command': self._DMR_RID_COMMANDS[command],
                'slot': int(args[0]),
                'dstId': int(args[1]),
            }

            if len(args) > 2 and args[2] is not None:
                payload['peerId'] = int(args[2])

            return RequestSpec(method='PUT', endpoint='/dmr/rid', payload=payload)

        if command in self._P25_RID_COMMANDS:
            if not args or args[0] is None:
                raise ValueError(f'{command} requires <rid>')

            payload: Dict[str, Any] = {
                'command': self._P25_RID_COMMANDS[command],
                'dstId': int(args[0]),
            }

            if command.endswith('dyn-regrp'):
                if len(args) < 2 or args[1] is None:
                    raise ValueError(f'{command} requires <rid> <tgid> [peerId]')
                payload['tgId'] = int(args[1])
                if len(args) > 2 and args[2] is not None:
                    payload['peerId'] = int(args[2])
            elif len(args) > 1 and args[1] is not None:
                payload['peerId'] = int(args[1])

            return RequestSpec(method='PUT', endpoint='/p25/rid', payload=payload)

        raise ValueError(f'Unknown command: {command}')
    
    def get_stats(self) -> Dict[str, Any]:
        """Get FNE statistics."""
        return self.call("fne-stats")
    
    def reload_rids(self) -> Dict[str, Any]:
        """Reload radio IDs."""
        return self.call("fne-reload-rids")
    
    def reload_talkgroups(self) -> Dict[str, Any]:
        """Reload talkgroups."""
        return self.call("fne-reload-tgs")
    
    def force_update(self) -> Dict[str, Any]:
        """Force update to peers."""
        return self.call("fne-force-update")
    
    def rid_inhibit(self, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Inhibit a radio ID."""
        return self.call("fne-p25-rid-inhibit", rid, peer_id)
    
    def rid_uninhibit(self, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Uninhibit a radio ID."""
        return self.call("fne-p25-rid-uninhibit", rid, peer_id)
    
    def rid_check(self, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Check radio ID status."""
        return self.call("fne-p25-rid-check", rid, peer_id)
    
    def rid_page(self, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Page a radio ID."""
        return self.call("fne-p25-rid-page", rid, peer_id)

    def dmr_rid_page(self, slot: int, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Page/call a DMR radio ID."""
        return self.call("fne-dmr-rid-page", slot, rid, peer_id)

    def dmr_rid_check(self, slot: int, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Radio-check a DMR radio ID."""
        return self.call("fne-dmr-rid-check", slot, rid, peer_id)

    def dmr_rid_inhibit(self, slot: int, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Inhibit a DMR radio ID."""
        return self.call("fne-dmr-rid-inhibit", slot, rid, peer_id)

    def dmr_rid_uninhibit(self, slot: int, rid: int, peer_id: Optional[int] = None) -> Dict[str, Any]:
        """Uninhibit a DMR radio ID."""
        return self.call("fne-dmr-rid-uninhibit", slot, rid, peer_id)

    def peer_reset_conn(self, peer_id: int) -> Dict[str, Any]:
        """Reset an upstream peer connection."""
        return self.call("fne-peer-reset-conn", peer_id)

    def peer_nak(self, peer_id: int, tag: str, reason: int) -> Dict[str, Any]:
        """Send an upstream peer NAK by peer ID."""
        return self.call("fne-peer-nak", peer_id, tag, reason)

    def peer_nak_addr(self, peer_id: int, tag: str, reason: int, address: str, port: int) -> Dict[str, Any]:
        """Send an upstream peer NAK by explicit address and port."""
        return self.call("fne-peer-nak-addr", peer_id, tag, reason, address, port)
