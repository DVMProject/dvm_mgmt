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
Configuration Management for DVM Management CLI
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
import re
from pydantic import BaseModel, Field, validator


class FederationNodeConfig(BaseModel):
    """Federated remote DVM Management web/API node definition."""

    id: str = Field(..., description="Unique federation node identifier")
    name: str = Field(..., description="Display name for the node")
    url: str = Field(..., description="Remote DVM Management web base URL")
    log_prefix_system: Optional[str] = Field(
        default=None,
        description="Remote node system log prefix used for UI display",
    )
    enabled: bool = Field(default=True, description="Enable this federation target")


class FNEHealthTargetConfig(BaseModel):
    """FNE REST endpoint polled by the dashboard health monitor."""

    id: str = Field(..., description="Unique health target identifier")
    name: str = Field(..., description="Display name for the FNE")
    host: str = Field(default="127.0.0.1", description="FNE REST API host")
    port: int = Field(default=9290, description="FNE REST API port")
    password: str = Field(default="RPT1234", description="FNE REST API password")
    use_ssl: bool = Field(default=False, description="Use HTTPS for this target")
    verify_ssl: bool = Field(default=False, description="Verify the target TLS certificate")
    enabled: bool = Field(default=True, description="Poll this health target")

    @validator('id', 'name', 'host')
    def nonempty_health_target_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class EditableConfigFile(BaseModel):
    """A configuration file explicitly exposed in the web editor."""

    id: str = Field(..., description="Stable identifier used by web routes")
    name: str = Field(..., description="Human-readable file name")
    path: Path = Field(..., description="Absolute path to the configuration file")

    @validator('id', 'name')
    def nonempty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @validator('path')
    def absolute_config_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("must be an absolute path")
        if value.suffix.lower() not in {'.yml', '.yaml', '.csv', '.dat'}:
            raise ValueError("must identify a .yml, .yaml, .csv, or .dat file")
        return value

    @property
    def format(self) -> str:
        """Return the validation/editor format selected by the file extension."""
        return "yaml" if self.path.suffix.lower() in {'.yml', '.yaml'} else "csv"


class ConsoleConfig(BaseModel):
    """Console configuration model."""
    
    # API Configuration
    system_port: int = Field(default=9290, description="System REST API port")
    system_acl: str = Field(default="RPT1234", description="System REST API password")
    api_host: str = Field(default="127.0.0.1", description="API host address")
    sysview_websocket_url: str = Field(
        default="ws://127.0.0.1:8443",
        description="Upstream websocket URL used by the browser System Watch page",
    )
    system_watch_enabled: bool = Field(
        default=True,
        description="Enable or disable the browser System Watch feature",
    )
    fne_health_targets: List[FNEHealthTargetConfig] = Field(
        default_factory=list,
        description="FNE REST endpoints monitored by the dashboard",
    )
    fne_health_timeout_sec: int = Field(
        default=3,
        description="Per-FNE dashboard health request timeout (seconds)",
    )

    # Federation Configuration
    federation_enabled: bool = Field(
        default=False,
        description="Enable server-to-server federation support",
    )
    federation_node_id: str = Field(
        default="local",
        description="Node identifier presented to remote federation peers",
    )
    federation_shared_secret: Optional[str] = Field(
        default=None,
        description="Global shared secret used for federation request signing",
    )
    federation_timeout_sec: int = Field(
        default=8,
        description="Federation upstream HTTP timeout (seconds)",
    )
    federation_auth_window_sec: int = Field(
        default=30,
        description="Federation request signature freshness window (seconds)",
    )
    federation_tls_verify: bool = Field(
        default=True,
        description="Enable TLS certificate verification for federation HTTP calls",
    )
    federation_nodes: List[FederationNodeConfig] = Field(
        default_factory=list,
        description="Configured federated remote DVM Management nodes",
    )
    # Web Configuration File Management
    editable_config_files: List[EditableConfigFile] = Field(
        default_factory=list,
        description="Explicit allowlist of files available in Configuration Management",
    )
    # File Paths
    system_tgid_acl_file: Optional[Path] = Field(
        default=Path("/opt/dvm/talkgroup_rules.yml"),
        description="System talkgroup ACL file"
    )
    system_rid_acl_file: Optional[Path] = Field(
        default=Path("/opt/dvm/rid_acl.dat"),
        description="System RID ACL file"
    )
    adj_site_map_file: Optional[Path] = Field(
        default=Path("/opt/dvm/adj_site_map.yml"),
        description="Adjacent site map YAML file"
    )
    system_peerid_acl_file: Optional[Path] = Field(
        default=Path("/opt/dvm/peer_list.dat"),
        description="System peer ID ACL file"
    )
    
    # Binaries
    dvm_bin_path: Path = Field(
        default=Path("/opt/dvm/bin"),
        description="DVM binaries directory"
    )
    tged_path: Optional[Path] = None
    peered_path: Optional[Path] = None
    
    # Log Configuration
    log_dir: Path = Field(
        default=Path("/var/log/dvm"),
        description="Log directory"
    )
    log_file: Path = Field(
        default=Path("/var/log/syslog"),
        description="System log file to search"
    )
    log_prefix_system: str = Field(
        default="SKYN-FNE1-CR1",
        description="Log prefix for system logs"
    )
    
    class Config:
        validate_assignment = True
        
    @validator('tged_path', always=True)
    def set_tged_path(cls, v: Optional[Path], values: Dict[str, Any]) -> Path:
        """Set default tged path if not specified."""
        if v is None:
            return values['dvm_bin_path'] / 'tged'
        return v
    
    @validator('peered_path', always=True)
    def set_peered_path(cls, v: Optional[Path], values: Dict[str, Any]) -> Path:
        """Set default peered path if not specified."""
        if v is None:
            return values['dvm_bin_path'] / 'peered'
        return v

    def enabled_fne_health_targets(self) -> List[FNEHealthTargetConfig]:
        """Return configured targets or the primary system as a fallback."""
        if self.fne_health_targets:
            return [target for target in self.fne_health_targets if target.enabled]
        return [FNEHealthTargetConfig(
            id="system",
            name="System FNE",
            host=self.api_host,
            port=self.system_port,
            password=self.system_acl,
        )]
    
    @classmethod
    def load_bash_config(cls, config_file: Path) -> 'ConsoleConfig':
        """Load configuration from bash-style config file."""
        config_data = {}
        federation_node_map: Dict[int, Dict[str, Any]] = {}
        fne_health_target_map: Dict[int, Dict[str, Any]] = {}
        editable_config_file_map: Dict[int, Dict[str, str]] = {}

        if not config_file.exists():
            # Return default config
            return cls()
        
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Parse KEY=value or KEY="value"
                match = re.match(r'^([A-Z0-9_]+)=(.+)$', line)
                if match:
                    key, value = match.groups()
                    # Remove quotes
                    value = value.strip('"').strip("'")

                    node_match = re.match(r'^FEDERATION_NODE_(\d+)_(ID|NAME|URL|ENABLED|LOG_PREFIX|LOG_PREFIX_SYSTEM)$', key)
                    if node_match:
                        index = int(node_match.group(1))
                        field = node_match.group(2)
                        bucket = federation_node_map.setdefault(index, {})
                        if field == 'ID':
                            bucket['id'] = value.strip()
                        elif field == 'NAME':
                            bucket['name'] = value.strip()
                        elif field == 'URL':
                            bucket['url'] = value.strip()
                        elif field in {'LOG_PREFIX', 'LOG_PREFIX_SYSTEM'}:
                            bucket['log_prefix_system'] = value.strip()
                        elif field == 'ENABLED':
                            normalized = value.strip().lower()
                            bucket['enabled'] = normalized in {'1', 'true', 'yes', 'on'}
                        continue

                    health_match = re.match(
                        r'^FNE_HEALTH_NODE_(\d+)_(ID|NAME|HOST|PORT|ACL|SSL|VERIFY_SSL|ENABLED)$',
                        key,
                    )
                    if health_match:
                        index = int(health_match.group(1))
                        field = health_match.group(2)
                        bucket = fne_health_target_map.setdefault(index, {})
                        if field in {'SSL', 'VERIFY_SSL', 'ENABLED'}:
                            bucket[{
                                'SSL': 'use_ssl',
                                'VERIFY_SSL': 'verify_ssl',
                                'ENABLED': 'enabled',
                            }[field]] = value.strip().lower() in {'1', 'true', 'yes', 'on'}
                        elif field == 'PORT':
                            bucket['port'] = int(value)
                        else:
                            bucket[{
                                'ID': 'id',
                                'NAME': 'name',
                                'HOST': 'host',
                                'ACL': 'password',
                            }[field]] = value.strip()
                        continue

                    config_file_match = re.match(r'^CONFIG_FILE_(\d+)_(NAME|PATH)$', key)
                    if config_file_match:
                        index = int(config_file_match.group(1))
                        field = config_file_match.group(2).lower()
                        editable_config_file_map.setdefault(index, {})[field] = value.strip()
                        continue

                    # Map bash variables to pydantic fields
                    key_map = {
                        'SYSTEM_PORT': 'system_port',
                        'SYSTEM_ACL': 'system_acl',
                        'API_HOST': 'api_host',
                        'FNE_HEALTH_TIMEOUT_SEC': 'fne_health_timeout_sec',
                        'SYSTEM_WATCH_WEBSOCKET_URL': 'sysview_websocket_url',
                        'SYSVIEW_WEBSOCKET_URL': 'sysview_websocket_url',
                        'SYSTEM_WATCH_ENABLED': 'system_watch_enabled',
                        'FEDERATION_ENABLED': 'federation_enabled',
                        'FEDERATION_NODE_ID': 'federation_node_id',
                        'FEDERATION_SHARED_SECRET': 'federation_shared_secret',
                        'FEDERATION_TIMEOUT_SEC': 'federation_timeout_sec',
                        'FEDERATION_AUTH_WINDOW_SEC': 'federation_auth_window_sec',
                        'FEDERATION_TLS_VERIFY': 'federation_tls_verify',
                        'SYSTEM_TGID_ACL_FILE': 'system_tgid_acl_file',
                        'SYSTEM_RID_ACL_FILE': 'system_rid_acl_file',
                        'SYSTEM_PEERID_ACL_FILE': 'system_peerid_acl_file',
                        'ADJ_SITE_MAP_FILE': 'adj_site_map_file',
                        'DVM_BIN_PATH': 'dvm_bin_path',
                        'TGED_PATH': 'tged_path',
                        'PEERED_PATH': 'peered_path',
                        'LOG_FILE': 'log_file',
                        'LOG_PREFIX_SYSTEM': 'log_prefix_system'
                    }
                    
                    if key in key_map:
                        pydantic_key = key_map[key]
                        # Convert to appropriate type
                        if pydantic_key.endswith('_port'):
                            config_data[pydantic_key] = int(value)
                        elif pydantic_key.endswith('_sec'):
                            config_data[pydantic_key] = int(value)
                        elif pydantic_key.endswith('_enabled'):
                            normalized = value.strip().lower()
                            if normalized in {'1', 'true', 'yes', 'on'}:
                                config_data[pydantic_key] = True
                            elif normalized in {'0', 'false', 'no', 'off'}:
                                config_data[pydantic_key] = False
                        elif pydantic_key.endswith('_verify'):
                            normalized = value.strip().lower()
                            if normalized in {'1', 'true', 'yes', 'on'}:
                                config_data[pydantic_key] = True
                            elif normalized in {'0', 'false', 'no', 'off'}:
                                config_data[pydantic_key] = False
                        elif pydantic_key.endswith('_path') or pydantic_key.endswith('_file') or 'profile' in pydantic_key:
                            config_data[pydantic_key] = Path(value)
                        else:
                            config_data[pydantic_key] = value

        if federation_node_map:
            nodes: List[Dict[str, Any]] = []
            for _, node in sorted(federation_node_map.items(), key=lambda item: item[0]):
                node_id = str(node.get('id', '')).strip()
                node_url = str(node.get('url', '')).strip()
                if not node_id or not node_url:
                    continue
                node_name = str(node.get('name') or node_id).strip()
                nodes.append({
                    'id': node_id,
                    'name': node_name,
                    'url': node_url,
                    'log_prefix_system': str(node.get('log_prefix_system', '')).strip() or None,
                    'enabled': bool(node.get('enabled', True)),
                })

            if nodes:
                config_data['federation_nodes'] = nodes

        if fne_health_target_map:
            targets: List[Dict[str, Any]] = []
            for index, target in sorted(fne_health_target_map.items()):
                target_id = str(target.get('id') or f"fne-{index}").strip()
                host = str(target.get('host') or config_data.get('api_host', '127.0.0.1')).strip()
                targets.append({
                    'id': target_id,
                    'name': str(target.get('name') or target_id).strip(),
                    'host': host,
                    'port': int(target.get('port', config_data.get('system_port', 9290))),
                    'password': str(target.get('password', config_data.get('system_acl', 'RPT1234'))),
                    'use_ssl': bool(target.get('use_ssl', False)),
                    'verify_ssl': bool(target.get('verify_ssl', False)),
                    'enabled': bool(target.get('enabled', True)),
                })
            config_data['fne_health_targets'] = targets

        if editable_config_file_map:
            editable_files: List[Dict[str, Any]] = []
            for index, item in sorted(editable_config_file_map.items()):
                name = item.get('name', '').strip()
                path = item.get('path', '').strip()
                if name and path:
                    editable_files.append({
                        'id': str(index),
                        'name': name,
                        'path': Path(path),
                    })
            config_data['editable_config_files'] = editable_files

        return cls(**config_data)
    
    @classmethod
    def load(cls, config_file: Optional[Path] = None) -> 'ConsoleConfig':
        """Load configuration from file."""
        if config_file is None:
            config_file = Path('/opt/console.conf')
        
        # Try loading as bash config first
        return cls.load_bash_config(config_file)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return self.dict()
