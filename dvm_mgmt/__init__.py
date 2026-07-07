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
DVM Management System - Unified CLI and TUI Management Tools
"""

__version__ = "1.0.0"
__author__ = "DVMProject Authors"
__license__ = "PROPRIETARY"

from dvm_mgmt.core.config import ConsoleConfig
from dvm_mgmt.core.api_client import DVMAPIClient

__all__ = [
    "ConsoleConfig",
    "DVMAPIClient",
    "__version__",
]
