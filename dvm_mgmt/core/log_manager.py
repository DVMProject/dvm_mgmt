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
Log Management for DVM Services
"""

from pathlib import Path
from typing import List, Optional, Iterator
from datetime import datetime
import re


class LogManager:
    """Manager for DVM service logs."""
    
    LOG_FILES = {
        'system': 'DVMHost.log',
        'fne': 'DVMFNE.log',
    }
    
    def __init__(self, log_dir: Path = Path('/var/log/dvm')):
        """
        Initialize log manager.
        
        Args:
            log_dir: Directory containing log files
        """
        self.log_dir = log_dir
    
    def get_log_path(self, log_type: str) -> Path:
        """Get path to a log file."""
        log_file = self.LOG_FILES.get(log_type)
        if not log_file:
            raise ValueError(f"Unknown log type: {log_type}")
        return self.log_dir / log_file
    
    def read_log(
        self,
        log_type: str,
        lines: Optional[int] = None,
        filter_pattern: Optional[str] = None,
        show_netsplit: bool = False,
        show_duplicates: bool = False
    ) -> List[str]:
        """
        Read log file with optional filtering.
        
        Args:
            log_type: Type of log to read
            lines: Number of lines to return (from end)
            filter_pattern: Regex pattern to filter lines
            show_netsplit: Show net split messages
            show_duplicates: Show duplicate connection drops
        
        Returns:
            List of log lines
        """
        log_path = self.get_log_path(log_type)
        
        if not log_path.exists():
            return [f"Log file not found: {log_path}"]
        
        result_lines = []
        
        try:
            with open(log_path, 'r') as f:
                for line in f:
                    # Apply filters
                    if not show_netsplit and 'net split' in line.lower():
                        continue
                    
                    if not show_duplicates and 'duplicate' in line.lower() and 'drop' in line.lower():
                        continue
                    
                    if filter_pattern:
                        if not re.search(filter_pattern, line, re.IGNORECASE):
                            continue
                    
                    result_lines.append(line.rstrip())
        
        except Exception as e:
            return [f"Error reading log: {e}"]
        
        # Return last N lines if specified
        if lines:
            return result_lines[-lines:]
        
        return result_lines
    
    def tail_log(self, log_type: str, lines: int = 50) -> List[str]:
        """Get last N lines of a log file."""
        return self.read_log(log_type, lines=lines)
    
    def search_log(self, log_type: str, pattern: str, max_results: int = 100) -> List[str]:
        """Search log for a pattern."""
        return self.read_log(log_type, filter_pattern=pattern)[:max_results]
    
    def get_log_size(self, log_type: str) -> int:
        """Get size of log file in bytes."""
        log_path = self.get_log_path(log_type)
        if log_path.exists():
            return log_path.stat().st_size
        return 0
    
    def get_all_logs_info(self) -> dict:
        """Get information about all log files."""
        info = {}
        
        for log_type, log_file in self.LOG_FILES.items():
            log_path = self.log_dir / log_file
            
            if log_path.exists():
                stat = log_path.stat()
                info[log_type] = {
                    'path': str(log_path),
                    'size_bytes': stat.st_size,
                    'size_mb': round(stat.st_size / 1024 / 1024, 2),
                    'modified': datetime.fromtimestamp(stat.st_mtime),
                    'exists': True
                }
            else:
                info[log_type] = {
                    'path': str(log_path),
                    'exists': False
                }
        
        return info
