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
Output formatting utilities
"""

from typing import List, Dict, Any
from datetime import datetime


def format_timestamp(ts: float) -> str:
    """
    Format a timestamp.
    
    Args:
        ts: Unix timestamp
    
    Returns:
        Formatted timestamp string
    """
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_bytes: Size in bytes
    
    Returns:
        Formatted size string
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    
    return f"{size_bytes:.1f} PB"


def format_table(
    headers: List[str],
    rows: List[List[Any]],
    alignments: Optional[List[str]] = None
) -> str:
    """
    Format data as a table.
    
    Args:
        headers: Column headers
        rows: Row data
        alignments: Column alignments ('left', 'right', 'center')
    
    Returns:
        Formatted table string
    """
    if not rows:
        return "No data"
    
    if alignments is None:
        alignments = ['left'] * len(headers)
    
    # Calculate column widths
    col_widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Build format strings
    fmt_strings = []
    for width, align in zip(col_widths, alignments):
        if align == 'right':
            fmt_strings.append(f"{{:>{width}}}")
        elif align == 'center':
            fmt_strings.append(f"{{:^{width}}}")
        else:
            fmt_strings.append(f"{{:<{width}}}")
    
    # Build table
    lines = []
    
    # Header
    header_line = "  ".join(
        fmt.format(str(h)) for fmt, h in zip(fmt_strings, headers)
    )
    lines.append(header_line)
    lines.append("-" * len(header_line))
    
    # Rows
    for row in rows:
        row_line = "  ".join(
            fmt.format(str(cell)) for fmt, cell in zip(fmt_strings, row)
        )
        lines.append(row_line)
    
    return "\n".join(lines)
