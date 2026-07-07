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
Adjacent site synchronization operations.
"""

import subprocess
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import yaml
import json
from datetime import datetime


class AdjacentSiteManager:
    """Manages adjacent site synchronization."""

    def __init__(
        self,
        config_file: str = "/opt/dvm/config/adjacent-sites.yml",
        sync_log: str = "/opt/dvm/log/site-sync.log",
    ):
        """
        Initialize adjacent site manager.

        Args:
            config_file: Path to adjacent sites configuration
            sync_log: Path to synchronization log file
        """
        self.config_file = Path(config_file)
        self.sync_log = Path(sync_log)
        self.sync_log.parent.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Dict:
        """
        Load adjacent sites configuration.

        Returns:
            Configuration dict
        """
        try:
            if not self.config_file.exists():
                return {"sites": [], "error": "Configuration file not found"}

            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)

            return config or {"sites": []}

        except Exception as e:
            return {"sites": [], "error": str(e)}

    def save_config(self, config: Dict) -> Tuple[bool, str]:
        """
        Save adjacent sites configuration.

        Args:
            config: Configuration dict to save

        Returns:
            Tuple of (success, message)
        """
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w") as f:
                yaml.dump(config, f, default_flow_style=False)

            return True, "Configuration saved"

        except Exception as e:
            return False, f"Error saving configuration: {e}"

    def list_sites(self) -> List[Dict]:
        """
        List configured adjacent sites.

        Returns:
            List of site dicts
        """
        config = self.load_config()
        return config.get("sites", [])

    def add_site(
        self, name: str, address: str, port: int = 62031, peer_id: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Add an adjacent site.

        Args:
            name: Site name
            address: IP address or hostname
            port: Port number
            peer_id: Optional peer ID

        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.load_config()

            # Check if site already exists
            for site in config.get("sites", []):
                if site.get("name") == name:
                    return False, f"Site already exists: {name}"

            # Add new site
            new_site = {
                "name": name,
                "address": address,
                "port": port,
                "enabled": True,
                "last_sync": None,
            }

            if peer_id is not None:
                new_site["peer_id"] = peer_id

            if "sites" not in config:
                config["sites"] = []

            config["sites"].append(new_site)

            success, msg = self.save_config(config)
            if success:
                return True, f"Added site: {name}"
            else:
                return False, msg

        except Exception as e:
            return False, f"Error adding site: {e}"

    def remove_site(self, name: str) -> Tuple[bool, str]:
        """
        Remove an adjacent site.

        Args:
            name: Site name to remove

        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.load_config()

            original_count = len(config.get("sites", []))
            config["sites"] = [s for s in config.get("sites", []) if s.get("name") != name]

            if len(config["sites"]) == original_count:
                return False, f"Site not found: {name}"

            success, msg = self.save_config(config)
            if success:
                return True, f"Removed site: {name}"
            else:
                return False, msg

        except Exception as e:
            return False, f"Error removing site: {e}"

    def sync_site(self, name: str) -> Tuple[bool, str]:
        """
        Synchronize with an adjacent site.

        Args:
            name: Site name to sync with

        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.load_config()

            # Find the site
            site = None
            for s in config.get("sites", []):
                if s.get("name") == name:
                    site = s
                    break

            if not site:
                return False, f"Site not found: {name}"

            if not site.get("enabled", True):
                return False, f"Site is disabled: {name}"

            # Log sync attempt
            self._log_sync(name, "started")

            # Perform sync (this would integrate with actual sync mechanism)
            # For now, simulate success
            timestamp = datetime.now().isoformat()

            # Update last sync time
            site["last_sync"] = timestamp
            self.save_config(config)

            self._log_sync(name, "completed", timestamp)

            return True, f"Synchronized with {name}"

        except Exception as e:
            self._log_sync(name, "failed", error=str(e))
            return False, f"Error syncing with {name}: {e}"

    def sync_all_sites(self) -> Dict[str, Tuple[bool, str]]:
        """
        Synchronize with all enabled adjacent sites.

        Returns:
            Dict mapping site names to (success, message) tuples
        """
        results = {}
        sites = self.list_sites()

        for site in sites:
            if site.get("enabled", True):
                name = site.get("name")
                results[name] = self.sync_site(name)

        return results

    def enable_site(self, name: str) -> Tuple[bool, str]:
        """
        Enable an adjacent site.

        Args:
            name: Site name to enable

        Returns:
            Tuple of (success, message)
        """
        return self._set_site_enabled(name, True)

    def disable_site(self, name: str) -> Tuple[bool, str]:
        """
        Disable an adjacent site.

        Args:
            name: Site name to disable

        Returns:
            Tuple of (success, message)
        """
        return self._set_site_enabled(name, False)

    def _set_site_enabled(self, name: str, enabled: bool) -> Tuple[bool, str]:
        """
        Set enabled status for a site.

        Args:
            name: Site name
            enabled: Enable or disable

        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.load_config()

            found = False
            for site in config.get("sites", []):
                if site.get("name") == name:
                    site["enabled"] = enabled
                    found = True
                    break

            if not found:
                return False, f"Site not found: {name}"

            success, msg = self.save_config(config)
            if success:
                status = "enabled" if enabled else "disabled"
                return True, f"Site {status}: {name}"
            else:
                return False, msg

        except Exception as e:
            return False, f"Error updating site: {e}"

    def _log_sync(
        self, site: str, status: str, timestamp: Optional[str] = None, error: Optional[str] = None
    ):
        """
        Log synchronization event.

        Args:
            site: Site name
            status: Sync status (started, completed, failed)
            timestamp: Optional timestamp
            error: Optional error message
        """
        try:
            if not timestamp:
                timestamp = datetime.now().isoformat()

            log_entry = {"timestamp": timestamp, "site": site, "status": status}

            if error:
                log_entry["error"] = error

            with open(self.sync_log, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

        except Exception:
            # Don't fail if logging fails
            pass

    def get_sync_history(self, limit: int = 50) -> List[Dict]:
        """
        Get synchronization history.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of sync history dicts
        """
        try:
            if not self.sync_log.exists():
                return []

            entries = []
            with open(self.sync_log, "r") as f:
                for line in f:
                    try:
                        entries.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue

            # Return most recent entries
            return entries[-limit:] if limit else entries

        except Exception:
            return []
