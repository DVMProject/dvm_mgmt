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
            system: Must be 'system'

        Returns:
            Result dictionary
        """
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.rid_inhibit(rid, peer_id)

    def uninhibit(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Uninhibit a radio ID.

        Args:
            rid: Radio ID to uninhibit
            peer_id: Optional peer ID
            system: Must be 'system'

        Returns:
            Result dictionary
        """
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.rid_uninhibit(rid, peer_id)

    def page(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Page a radio ID.

        Args:
            rid: Radio ID to page
            peer_id: Optional peer ID
            system: Must be 'system'

        Returns:
            Result dictionary
        """
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.rid_page(rid, peer_id)

    def check(
        self, rid: int, peer_id: Optional[int] = None, system: str = "system"
    ) -> Dict[str, Any]:
        """
        Check radio ID status.

        Args:
            rid: Radio ID to check
            peer_id: Optional peer ID
            system: Must be 'system'

        Returns:
            Result dictionary
        """
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.rid_check(rid, peer_id)

    def get_operation(
        self, operation_id: int, system: str = "system"
    ) -> Dict[str, Any]:
        """Return the current state of a subscriber operation."""
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.get_subscriber_operation(operation_id)

    def get_operations(
        self, count: int = 50, system: str = "system"
    ) -> Dict[str, Any]:
        """Return the most recent subscriber operations."""
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return self.system_api.get_subscriber_operations(count)

    def reload(self, system: str = "system") -> Dict[str, Any]:
        """
        Reload radio IDs from file.

        Args:
            system: Must be 'system'

        Returns:
            Result dictionary
        """
        if system != "system":
            raise ValueError(f"Invalid system type: {system}")
        return {
            "system": self.system_api.reload_rids(),
            "system_update": self.system_api.force_update(),
        }
