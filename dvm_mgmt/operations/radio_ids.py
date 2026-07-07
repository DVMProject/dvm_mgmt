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
Radio ID Operations
"""

from typing import Optional, Dict, Any
from dvm_mgmt.core.api_client import DVMAPIClient
from dvm_mgmt.core.config import ConsoleConfig


class RadioIDManager:
    """Manager for radio ID operations."""

    def __init__(self, config: ConsoleConfig):
        """
        Initialize RID manager.

        Args:
            config: Console configuration
        """
        self.config = config
        self.system_api = DVMAPIClient(
            host=config.api_host,
            port=config.system_port,
            password=config.system_acl,
        )

    def inhibit(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Inhibit a radio ID.

        Args:
            rid: Radio ID to inhibit
            peer_id: Optional peer ID
            system: System type ('system' or 'issi')

        Returns:
            Result dictionary
        """
        api = self.system_api if system == "system" else self.issi_api
        return api.rid_inhibit(rid, peer_id)

    def uninhibit(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Uninhibit a radio ID.

        Args:
            rid: Radio ID to uninhibit
            peer_id: Optional peer ID
            system: System type ('system' or 'issi')

        Returns:
            Result dictionary
        """
        api = self.system_api if system == "system" else self.issi_api
        return api.rid_uninhibit(rid, peer_id)

    def page(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Page a radio ID.

        Args:
            rid: Radio ID to page
            peer_id: Optional peer ID
            system: System type ('system' or 'issi')

        Returns:
            Result dictionary
        """
        api = self.system_api if system == "system" else self.issi_api
        return api.rid_page(rid, peer_id)

    def check(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Check radio ID status.

        Args:
            rid: Radio ID to check
            peer_id: Optional peer ID
            system: System type ('system' or 'issi')

        Returns:
            Result dictionary
        """
        api = self.system_api if system == "system" else self.issi_api
        return api.rid_check(rid, peer_id)

    def reload(self, system: str = "both") -> Dict[str, Any]:
        """
        Reload radio IDs from file.

        Args:
            system: System to reload ('system', 'issi', or 'both')

        Returns:
            Result dictionary
        """
        results = {}

        if system in ("system", "both"):
            results["system"] = self.system_api.reload_rids()
            results["system_update"] = self.system_api.force_update()

        if system in ("issi", "both"):
            results["issi"] = self.issi_api.reload_rids()

        return results
