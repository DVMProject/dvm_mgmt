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
Talkgroup Management Operations
"""

import subprocess
from typing import Optional, Dict, Any
from pathlib import Path
from dvm_mgmt.core.api_client import DVMAPIClient
from dvm_mgmt.core.config import ConsoleConfig


class TalkgroupManager:
    """Manager for talkgroup operations."""

    def __init__(self, config: ConsoleConfig):
        """
        Initialize talkgroup manager.

        Args:
            config: Console configuration
        """
        self.config = config
        self.system_api = DVMAPIClient(
            host=config.api_host,
            port=config.system_port,
            password=config.system_acl,
        )

    def edit_system_talkgroups(self) -> bool:
        """
        Launch talkgroup editor for system talkgroups.

        Returns:
            True if editor launched successfully
        """
        if not self.config.system_tgid_acl_file.exists():
            raise FileNotFoundError(
                f"System talkgroup file not found: {self.config.system_tgid_acl_file}"
            )

        try:
            subprocess.run(
                [str(self.config.tged_path), "-c", str(self.config.system_tgid_acl_file)],
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def reload(self, system: str = "both") -> Dict[str, Any]:
        """
        Reload talkgroups from file.

        Args:
            system: System to reload ('system', 'issi', or 'both')

        Returns:
            Result dictionary
        """
        results = {}

        if system in ("system", "both"):
            results["system"] = self.system_api.reload_talkgroups()
            results["system_update"] = self.system_api.force_update()

        if system in ("issi", "both"):
            results["issi"] = self.issi_api.reload_talkgroups()

        return results
