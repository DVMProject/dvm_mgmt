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
DVM Management CLI - Main Entry Point
"""

import sys
import argparse
from pathlib import Path


def format_dependency_error(exc: ImportError) -> str | None:
    """Return a user-facing dependency error for common deployment mismatches."""
    message = str(exc)

    if "No module named 'fastapi'" in message:
        return (
            "Web mode requires FastAPI, which is not installed for this interpreter.\n"
            "On Debian 12 with system packages, install `python3-fastapi` and `python3-pydantic`."
        )

    if "Undefined" in message and "pydantic.fields" in message:
        return (
            "Web mode detected an incompatible FastAPI/Pydantic install.\n"
            "Debian 12 expects FastAPI 0.92.x with Pydantic 1.10.x from the system packages.\n"
            "The failing path points at `/usr/local`, so a pip-installed package is likely shadowing Debian's modules.\n"
            "Remove the `/usr/local` FastAPI/Pydantic packages or install a matching pair together."
        )

    return None


def detect_terminal_capability() -> str:
    """Detect if terminal supports TUI."""
    try:
        import os
        if not sys.stdout.isatty():
            return "cli"
        term = os.environ.get("TERM", "")
        if "dumb" in term or term == "":
            return "cli"
        try:
            import shutil
            columns, rows = shutil.get_terminal_size()
            if columns < 80 or rows < 24:
                return "cli"
        except Exception:
            return "cli"
        return "tui"
    except Exception:
        return "cli"


def main() -> int:
    """Main entry point for DVM management tools."""
    parser = argparse.ArgumentParser(
        description="DVM Management Tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  run                         # Auto-detect best interface
  run --mode cli              # Force CLI mode
  run --mode web              # Start web interface (default port 8080)
  run --mode web --web-port 9090
  run --mode web --web-foreground-logs
  run --mode web --web-log-level debug
  run --config /path          # Use custom config file

Copyright (C) 2026 DVMProject Authors
        """
    )

    parser.add_argument(
        "--mode",
        choices=["cli", "web", "auto"],
        default="auto",
        help="Interface mode (default: auto-detect)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default="/opt/console.conf",
        help="Configuration file path (default: /opt/console.conf)",
    )
    parser.add_argument(
        "--web-host",
        default="0.0.0.0",
        help="Web interface bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8080,
        help="Web interface port (default: 8080)",
    )
    parser.add_argument(
        "--web-foreground-logs",
        action="store_true",
        help="Write Uvicorn web logs to the foreground instead of syslog",
    )
    parser.add_argument(
        "--web-log-level",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        default="info",
        help="Uvicorn web log level (default: info)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to execute (non-interactive mode)",
    )

    args = parser.parse_args()

    mode = args.mode
    if mode == "auto" and args.command:
        mode = "cli"
    elif mode == "auto":
        mode = detect_terminal_capability()

    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    try:
        if mode == "web":
            try:
                from dvm_mgmt.web.app import main as web_main
            except ImportError as exc:
                dependency_error = format_dependency_error(exc)
                if dependency_error is not None:
                    print(f"\nERROR: {dependency_error}", file=sys.stderr)
                    return 1
                raise
            return web_main(
                config_file=args.config,
                host=args.web_host,
                port=args.web_port,
                foreground_logs=args.web_foreground_logs,
                log_level=args.web_log_level,
            )
        else:
            from dvm_mgmt.cli.cisco_cli import main as cli_main
            command = " ".join(args.command) if args.command else None
            return cli_main(config_file=args.config, command=command)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        return 130
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
