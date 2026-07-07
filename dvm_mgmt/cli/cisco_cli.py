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
Cisco IOS-style CLI for DVM
"""

import sys
import cmd2
from cmd2 import Cmd, with_argparser
import argparse
import re
import glob
import socket
from pathlib import Path
from typing import Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from dvm_mgmt.core.config import ConsoleConfig
from dvm_mgmt.core.process_manager import ProcessManager
from dvm_mgmt.core.log_manager import LogManager
from dvm_mgmt.core.api_client import DVMAPIClient
from dvm_mgmt.operations.radio_ids import RadioIDManager
from dvm_mgmt.operations.talkgroups import TalkgroupManager
from dvm_mgmt.operations.peers import PeerManager


class DVMMgmtCLI(Cmd):
    """DVM Management Console - Cisco IOS-style CLI"""
    
    # intro is printed manually in main() before cmdloop
    intro = ""
    
    def __init__(self, config: ConsoleConfig, *args, **kwargs):
        """Initialize CLI."""
        # Save and clear sys.argv to prevent cmd2 from interpreting
        # command-line arguments as commands
        self._original_argv = sys.argv.copy()
        sys.argv = [sys.argv[0]]  # Keep only program name
        
        # Remove intro from kwargs if present (it's a class attribute, not an __init__ param)
        kwargs.pop('intro', None)
        
        super().__init__(*args, **kwargs)
        
        self.config = config
        self.console = Console()
        
        # Initialize managers
        self.process_mgr = ProcessManager()
        self.log_mgr = LogManager(config.log_dir)
        self.rid_mgr = RadioIDManager(config)
        self.tg_mgr = TalkgroupManager(config)
        self.peer_mgr = PeerManager(config)
        self.system_api = DVMAPIClient(
            host=config.api_host,
            port=config.system_port,
            password=config.system_acl,
        )
        
        # Mode tracking
        self.privileged_mode = False
        
        # Set initial prompt with system hostname
        hostname = socket.gethostname()
        self.prompt = f'{hostname}> '
        
        # Disable default cmd2 features we don't want
        self.allow_cli_args = False
        
        # Hide scripting commands from help
        self.hidden_commands.extend(['run_pyscript', 'run_script'])
        
        # Restore original sys.argv after cmd2 initialization
        sys.argv = self._original_argv
    
    def onecmd_plus_hooks(self, line, **kwargs):
        """Override to intercept '?' before argparse processes it and check feature availability."""
        # Check if line ends with '?'
        if line.strip().endswith('?'):
            # Remove the '?' and get the command
            cmd_line = line.strip()[:-1].strip()
            if cmd_line:
                # Show help for the specific command
                self.do_help(cmd_line)
            else:
                # Just '?' - show general help
                self.do_help('')
            return False  # Stop processing this command
        
        # Continue normal processing
        return super().onecmd_plus_hooks(line, **kwargs)
    
    def default(self, statement):
        """Handle unrecognized commands and '?' for help."""
        line = str(statement).strip()
        
        # Check if line ends with '?'
        if line.endswith('?'):
            # Remove the '?' and get the command
            cmd_line = line[:-1].strip()
            if cmd_line:
                # Show help for the specific command
                self.do_help(cmd_line)
            else:
                # Just '?' - show general help
                self.do_help('')
            return
        
        # Call parent default for truly unrecognized commands
        return super().default(statement)
    
    def do_help(self, arg):
        """Custom help command that categorizes by privilege level."""
        if arg:
            # Show help for specific command
            return super().do_help(arg)
        
        # Define which commands require privileged mode
        privileged_commands = {
            'restart', 'rid', 'talkgroup', 'peer', 'fne'
        }
        
        # Get all commands
        commands = self.get_all_commands()
        
        # Categorize commands
        user_cmds = []
        priv_cmds = []
        
        for cmd in sorted(commands):
            # Skip hidden commands and private methods
            if cmd in self.hidden_commands or cmd.startswith('_'):
                continue
            
            # Get the docstring
            doc = getattr(self, 'do_' + cmd).__doc__ or ''
            doc = doc.split('\n')[0].strip()
            
            # Categorize
            if cmd in privileged_commands:
                priv_cmds.append((cmd, doc))
            else:
                user_cmds.append((cmd, doc))
        
        # Display user mode commands
        self.console.print("[bold cyan]User Mode Commands:[/bold cyan]")
        self.console.print("─" * 70)
        for cmd, doc in user_cmds:
            self.console.print(f"  {cmd:20s} {doc}")
        
        # Display privileged mode commands
        self.console.print(f"\n[bold yellow]Privileged Mode Commands (require 'enable'):[/bold yellow]")
        self.console.print("─" * 70)
        for cmd, doc in priv_cmds:
            self.console.print(f"  {cmd:20s} {doc}")
        
        self.console.print("\nType 'help <command>' for detailed help on a specific command.")
        self.console.print("Type 'enable' to enter privileged mode.\n")
    
    # ========== Mode Commands ==========
    
    def do_enable(self, _):
        """Enter privileged mode"""
        if self.privileged_mode:
            self.poutput("Already in privileged mode.")
            return
        
        self.privileged_mode = True
        hostname = socket.gethostname()
        self.prompt = f'{hostname}# '
        self.poutput("Privileged mode enabled.")
    
    def do_en(self, args):
        """Alias for 'enable' command"""
        return self.do_enable(args)
    
    def do_disable(self, _):
        """Exit privileged mode"""
        if not self.privileged_mode:
            self.poutput("Not in privileged mode.")
            return
        
        self.privileged_mode = False
        hostname = socket.gethostname()
        self.prompt = f'{hostname}> '
        self.poutput("Privileged mode disabled.")
    
    def do_dis(self, args):
        """Alias for 'disable' command"""
        return self.do_disable(args)
    
    # ========== Show Commands ==========
    
    show_parser = argparse.ArgumentParser()
    show_subparsers = show_parser.add_subparsers(title='show commands', dest='show_cmd')
    
    # show version
    show_version_parser = show_subparsers.add_parser('version', help='Show system version')
    
    # show logs
    show_logs_parser = show_subparsers.add_parser('logs', help='Show system logs')
    show_logs_parser.add_argument('type', choices=['system', 'public', 'las-internet', 'las-wifi', 'rc'])
    show_logs_parser.add_argument('--lines', '-n', type=int, default=50, help='Number of lines to show')
    show_logs_parser.add_argument('--netsplit', action='store_true', help='Show netsplit logs')
    show_logs_parser.add_argument('--duplicates', action='store_true', help='Show duplicate connection drops')
    show_logs_parser.add_argument('--unauthorized', action='store_true', help='Show unauthorized access logs')
    
    # show pids
    show_pids_parser = show_subparsers.add_parser('pids', help='Show running processes')
    show_pids_parser.add_argument('--all', '-a', action='store_true', help='Show all processes including watchdog')
    show_pids_parser.add_argument('--workers', '-w', action='store_true', help='Show worker threads')
    show_pids_parser.add_argument('--threads', '-t', action='store_true', help='Show thread details')
    
    # show stats
    show_stats_parser = show_subparsers.add_parser('stats', help='Show FNE statistics')
    
    # show peers
    show_peers_parser = show_subparsers.add_parser('peers', help='Show peers')
    show_peers_parser.add_argument('--system', choices=['system', 'public', 'both'], default='both')
    show_peers_parser.add_argument('--show-passwords', action='store_true', help='Show passwords in plain text')
    
    # show spanning-tree
    show_spanningtree_parser = show_subparsers.add_parser('spanning-tree', help='Show network spanning tree topology')
    
    # show memory
    show_memory_parser = show_subparsers.add_parser('memory', help='Show system memory usage')
    
    @with_argparser(show_parser)
    def do_show(self, args):
        """Show running system information"""
        if not args.show_cmd:
            self.do_help('show')
            return
        
        if args.show_cmd == 'version':
            self._show_version()
        elif args.show_cmd == 'logs':
            self._show_logs(args.type, args.lines,
                          netsplit=getattr(args, 'netsplit', False),
                          duplicates=getattr(args, 'duplicates', False),
                          unauthorized=getattr(args, 'unauthorized', False))
        elif args.show_cmd == 'pids':
            self._show_processes(
                show_all=getattr(args, 'all', False),
                show_workers=getattr(args, 'workers', False),
                show_threads=getattr(args, 'threads', False)
            )
        elif args.show_cmd == 'stats':
            self._show_stats()
        elif args.show_cmd == 'peers':
            if not self._check_feature_available('peer'):
                self._subprime_unavailable()
                return
            # Check if show-passwords flag is used without privileged mode
            if getattr(args, 'show_passwords', False) and not self.privileged_mode:
                self.perror("--show-passwords requires privileged mode.")
                return
            self._show_peers(args.system, getattr(args, 'show_passwords', False))
        elif args.show_cmd == 'spanning-tree':
            self._show_spanning_tree()
        elif args.show_cmd == 'memory':
            self._show_memory()
    
    def do_sh(self, args):
        """Alias for 'show' command"""
        self.do_show(args)
    
    def _show_version(self):
        """Show version information."""
        from dvm_mgmt import __version__
        self.poutput(f"\nDVM Management CLI Version {__version__}")
        self.poutput(f"Copyright (C) 2026 DVMProject Authors\n")
    
    def _show_logs(self, log_type: str, lines: int, netsplit: bool = False, duplicates: bool = False, unauthorized: bool = False):
        """Show log file contents with filtering options."""
        try:
            # For system/public logs, always use the log_viewer module from configuration
            from dvm_mgmt.core.log_viewer import view_syslog_fne
            
            # Determine if we're viewing system or public logs
            system_only = (log_type == 'system')
            
            # Call the log viewer with configuration values
            if netsplit:
                view_syslog_fne(system_only=system_only, netsplit=True, scrollback=lines,
                                log_file=str(self.config.log_file),
                                log_prefix_system=self.config.log_prefix_system,
                                log_prefix_public=self.config.log_prefix_public)
            elif duplicates:
                view_syslog_fne(system_only=system_only, duplicates=True, scrollback=lines,
                                log_file=str(self.config.log_file),
                                log_prefix_system=self.config.log_prefix_system,
                                log_prefix_public=self.config.log_prefix_public)
            elif unauthorized:
                view_syslog_fne(system_only=system_only, unauthorized=True, scrollback=lines,
                                log_file=str(self.config.log_file),
                                log_prefix_system=self.config.log_prefix_system,
                                log_prefix_public=self.config.log_prefix_public)
            else:
                view_syslog_fne(system_only=system_only, tail=tail, scrollback=lines,
                                log_file=str(self.config.log_file),
                                log_prefix_system=self.config.log_prefix_system,
                                log_prefix_public=self.config.log_prefix_public)
        
        except KeyboardInterrupt:
            # User pressed Ctrl+C to stop tailing
            self.poutput("\n\nLog tailing stopped.")
        except Exception as e:
            self.perror(f"Error reading log: {e}")
    
    def _show_processes(self, show_all: bool = False, show_workers: bool = False, show_threads: bool = False):
        """Show detailed process and thread information similar to show-pids.sh"""
        import subprocess
        
        # Display system top info
        try:
            top_result = subprocess.run(['top', '-n1', '-b', '-1', '-p0'], 
                                      capture_output=True, text=True, timeout=5)
            if top_result.returncode == 0:
                lines = top_result.stdout.split('\n')
                # Show first few lines with system info
                for i, line in enumerate(lines[:5]):
                    if line.strip():
                        self.poutput(line)
                self.poutput("")
        except Exception as e:
            self.perror(f"Failed to get system info: {e}")
        
        # Display processes
        self.poutput("=" * 80)
        self.poutput("PROCESSES")
        self.poutput("=" * 80)
        
        try:
            ps_cmd = ['ps', '-eo', 'pid,comm,lstart,etime,%cpu,%mem,rsz,vsz,args']
            ps_result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=5)
            
            if ps_result.returncode == 0:
                lines = ps_result.stdout.split('\n')
                header = lines[0] if lines else ""
                self.poutput(header)
                
                for line in lines[1:]:
                    if not line.strip():
                        continue
                    
                    # Filter for dvm processes
                    if any(proc in line for proc in ['dvmfne', 'dvmlas', 'dvmrc', 'sysview']):
                        # Skip grep and watchdog unless --all specified
                        if not show_all:
                            if 'grep' in line or 'watchdog' in line:
                                continue
                        self.poutput(line)
                        
        except Exception as e:
            self.perror(f"Failed to get process list: {e}")
        
        # Display threads if requested
        if show_threads:
            self.poutput("")
            self.poutput("=" * 80)
            self.poutput("THREADS")
            self.poutput("=" * 80)
            
            try:
                ps_cmd = ['ps', '-eTo', 'pid,spid,comm,lstart,etime,%cpu,%mem,rsz,vsz']
                ps_result = subprocess.run(ps_cmd, capture_output=True, text=True, timeout=5)
                
                if ps_result.returncode == 0:
                    lines = ps_result.stdout.split('\n')
                    header = lines[0] if lines else ""
                    self.poutput(header)
                    
                    for line in lines[1:]:
                        if not line.strip():
                            continue
                        
                        # Filter for dvm processes and main threads
                        thread_patterns = ['dvmfne', 'sysview', 'host:', 'fne:']
                        worker_patterns = [':worker', ':rx-pckt', ':diag-rx-pckt']
                        
                        has_thread_pattern = any(pattern in line for pattern in thread_patterns)
                        has_worker_pattern = any(pattern in line for pattern in worker_patterns)
                        
                        # Show worker threads only if --workers specified
                        if has_worker_pattern and not show_workers:
                            continue
                        
                        if has_thread_pattern or has_worker_pattern:
                            # Skip grep unless --all specified
                            if not show_all and 'grep' in line:
                                continue
                            self.poutput(line)
                            
            except Exception as e:
                self.perror(f"Failed to get thread list: {e}")
    
    def _show_stats(self):
        """Show FNE statistics."""
        try:
            result = self.system_api.call('fne-stats')
            
            if not result.get('success'):
                self.perror(f"Failed to get stats: {result.get('error', 'Unknown error')}")
                return
            
            # Get FNE version separately
            version_result = self.system_api.call('version')
            fne_version = version_result.get('version', 'N/A') if version_result.get('success') else 'N/A'
            
            self._format_stats_output(result, fne_version)
        
        except Exception as e:
            self.perror(f"Error getting stats: {e}")

    def _show_spanning_tree(self):
        """Show network spanning tree topology."""
        try:
            result = self.system_api.call('fne-spanning-tree')
            
            if not result.get('success'):
                self.perror(f"Failed to get spanning tree: {result.get('error', 'Unknown error')}")
                return
            
            self._format_spanning_tree_output(result)
        
        except Exception as e:
            self.perror(f"Error getting spanning tree: {e}")

    def _show_memory(self):
        """Show system memory usage via 'free -m'."""
        import subprocess
        try:
            result = subprocess.run(['free', '-m'], capture_output=True, text=True)
            self.poutput(result.stdout)
        except Exception as e:
            self.perror(f"Error retrieving memory info: {e}")

    
    def _show_peers(self, system: str, show_passwords: bool = False):
        """Show peers.
        
        Args:
            system: Which peer system to show ('system', 'public', or 'both')
            show_passwords: If True, show passwords in plain text instead of masked
        """
        try:
            if system in ['system', 'both']:
                peers = self.peer_mgr.list_peers('system')
                # Sort by peer ID like bash script does
                peers.sort(key=lambda x: x.get('id', 0))
                
                table = Table(title="System Peers")
                table.add_column("Peer Name", style="yellow")
                table.add_column("Peer ID", style="cyan", justify="right")
                table.add_column("Password", style="magenta")
                table.add_column("Replica", justify="center")
                table.add_column("Req Key", justify="center")
                table.add_column("Can Inh", justify="center")
                table.add_column("Call Pri", justify="right")
                table.add_column("Jitter", justify="right")
                table.add_column("Max Size", justify="right")
                table.add_column("Max Wait", justify="right")
                
                for peer in peers:
                    # Conditionally mask password based on show_passwords flag
                    password = peer.get('password', '')
                    if show_passwords:
                        display_pwd = password
                    else:
                        # Mask password - show first 3 and last 3 chars with asterisks in middle
                        if len(password) > 6:
                            display_pwd = password[:3] + '*' * (len(password) - 6) + password[-3:]
                        elif len(password) > 0:
                            display_pwd = '*' * len(password)
                        else:
                            display_pwd = ''
                    
                    table.add_row(
                        peer.get('name', 'N/A')[:30],  # Truncate to 30 chars like bash
                        str(peer.get('id', 'N/A')),
                        display_pwd[:30],  # Truncate to 30 chars
                        str(peer.get('replica', 0)),
                        str(peer.get('require_key', 0)),
                        str(peer.get('can_inhibit', 0)),
                        str(peer.get('call_priority', 0)),
                        str(peer.get('jitter', 360)),
                        str(peer.get('max_size', 12582912)),
                        str(peer.get('max_wait', 25))
                    )
                
                self.console.print(table)
            
            if system in ['public', 'both']:
                peers = self.peer_mgr.list_peers('public')
                # Sort by peer ID like bash script does
                peers.sort(key=lambda x: x.get('id', 0))
                
                table = Table(title="Public Peers")
                table.add_column("Peer Name", style="yellow")
                table.add_column("Peer ID", style="cyan", justify="right")
                table.add_column("Password", style="magenta")
                table.add_column("Replica", justify="center")
                table.add_column("Req Key", justify="center")
                table.add_column("Can Inh", justify="center")
                table.add_column("Call Pri", justify="right")
                table.add_column("Jitter", justify="right")
                table.add_column("Max Size", justify="right")
                table.add_column("Max Wait", justify="right")
                
                for peer in peers:
                    # Conditionally mask password based on show_passwords flag
                    password = peer.get('password', '')
                    if show_passwords:
                        display_pwd = password
                    else:
                        # Mask password - show first 3 and last 3 chars with asterisks in middle
                        if len(password) > 6:
                            display_pwd = password[:3] + '*' * (len(password) - 6) + password[-3:]
                        elif len(password) > 0:
                            display_pwd = '*' * len(password)
                        else:
                            display_pwd = ''
                    
                    table.add_row(
                        peer.get('name', 'N/A')[:30],  # Truncate to 30 chars like bash
                        str(peer.get('id', 'N/A')),
                        display_pwd[:30],  # Truncate to 30 chars
                        str(peer.get('replica', 0)),
                        str(peer.get('require_key', 0)),
                        str(peer.get('can_inhibit', 0)),
                        str(peer.get('call_priority', 0)),
                        str(peer.get('jitter', 360)),
                        str(peer.get('max_size', 12582912)),
                        str(peer.get('max_wait', 25))
                    )
                
                self.console.print(table)
        except Exception as e:
            self.perror(f"Error: {e}")
    
    # ========== Radio Commands ==========
    
    radio_parser = argparse.ArgumentParser()
    radio_subparsers = radio_parser.add_subparsers(title='radio commands', dest='radio_cmd')
    
    # radio inhibit
    inhibit_parser = radio_subparsers.add_parser('inhibit', help='Inhibit a radio ID')
    inhibit_parser.add_argument('rid', type=int, help='Radio ID')
    inhibit_parser.add_argument('--peer-id', type=int, help='Peer ID')
    
    # radio uninhibit
    uninhibit_parser = radio_subparsers.add_parser('uninhibit', help='Uninhibit a radio ID')
    uninhibit_parser.add_argument('rid', type=int, help='Radio ID')
    uninhibit_parser.add_argument('--peer-id', type=int, help='Peer ID')
    
    # radio page
    page_parser = radio_subparsers.add_parser('page', help='Page a radio ID')
    page_parser.add_argument('rid', type=int, help='Radio ID')
    page_parser.add_argument('--peer-id', type=int, help='Peer ID')
    
    # radio check
    check_parser = radio_subparsers.add_parser('check', help='Check radio ID status')
    check_parser.add_argument('rid', type=int, help='Radio ID')
    check_parser.add_argument('--peer-id', type=int, help='Peer ID')
    
    @with_argparser(radio_parser)
    def do_radio(self, args):
        """Radio operations"""
        if not args.radio_cmd:
            self.do_help('radio')
            return
        
        # Only inhibit and uninhibit require privilege mode
        # Page and check can be executed without privileges
        if args.radio_cmd in ('inhibit', 'uninhibit'):
            if not self.privileged_mode:
                self.perror("Command requires privileged mode.")
                return
        
        try:
            if args.radio_cmd == 'inhibit':
                # Warning prompt for inhibit operation
                peer_info = f" on peer {args.peer_id}" if args.peer_id else ""
                warning_msg = f"""
WARNING: You are about to inhibit RID {args.rid}{peer_info}!

This will disable the radio and prevent it from transmitting.
Are you sure you wish to continue?

Press [Enter] to continue or Ctrl+C to cancel: """
                
                try:
                    input(warning_msg)
                except KeyboardInterrupt:
                    self.poutput("\n[ABORTD] Inhibit operation cancelled")
                    return
                
                result = self.rid_mgr.inhibit(args.rid, args.peer_id, args.system)
            elif args.radio_cmd == 'uninhibit':
                result = self.rid_mgr.uninhibit(args.rid, args.peer_id, args.system)
            elif args.radio_cmd == 'page':
                result = self.rid_mgr.page(args.rid, args.peer_id, args.system)
            elif args.radio_cmd == 'check':
                result = self.rid_mgr.check(args.rid, args.peer_id, args.system)
            else:
                return
            
            if result.get('success', True):
                self.poutput(f"[  OK  ] Radio {args.radio_cmd} successful for RID {args.rid}")
            else:
                self.perror(f"[FAILED] {result.get('error', 'Unknown error')}")
        
        except Exception as e:
            self.perror(f"Error: {e}")
    
    # ========== Talkgroup Commands ==========
    
    talkgroup_parser = argparse.ArgumentParser()
    talkgroup_subparsers = talkgroup_parser.add_subparsers(title='talkgroup commands', dest='talkgroup_cmd')
    
    # talkgroup edit
    edit_tg_parser = talkgroup_subparsers.add_parser('edit', help='Edit talkgroups interactively')
    
    @with_argparser(talkgroup_parser)
    def do_talkgroup(self, args):
        """Talkgroup management"""
        if not self._check_feature_available('talkgroup_edit'):
            self._subprime_unavailable()
            return
        
        if not self.privileged_mode:
            self.perror("Command requires privileged mode.")
            return
        
        if not args.talkgroup_cmd:
            self.do_help('talkgroup')
            return
        
        try:
            if args.talkgroup_cmd == 'edit':
                success = self.tg_mgr.edit_system_talkgroups()
                if success:
                    self.poutput("[  OK  ] System talkgroups edited")
                else:
                    self.perror("[FAILED] Failed to edit system talkgroups")
        
        except FileNotFoundError as e:
            self.perror(f"[FAILED] {e}")
        except Exception as e:
            self.perror(f"Error: {e}")
    
    # ========== System Management ==========
    
    reload_parser = argparse.ArgumentParser()
    reload_parser.add_argument('target', choices=['service', 'rids', 'talkgroups', 'peer-list', 'crypto'])
    reload_parser.add_argument('name', nargs='?', help='Service name (fne, sysview)')
    
    @with_argparser(reload_parser)
    def do_reload(self, args):
        """Reload service or configuration"""
        if not self.privileged_mode:
            self.perror("Command requires privileged mode.")
            return
        
        try:
            if args.target == 'service':
                if not args.name:
                    self.perror("Service name required")
                    return

                if args.name == 'sysview' and not self.config.system_watch_enabled:
                    self.perror("System Watch is disabled; sysview restart is unavailable.")
                    return

                if not self.process_mgr.is_service_supported(args.name):
                    self.perror(f"Unknown service '{args.name}'")
                    return
                
                self.poutput(f"Restarting {args.name}...")
                if self.process_mgr.restart_service(args.name):
                    self.poutput(f"[  OK  ] Service {args.name} restarted")
                else:
                    self.perror(f"[FAILED] Failed to restart {args.name}")
            
            elif args.target == 'rids':
                self.poutput("Reloading radio IDs...")
                result = self.rid_mgr.reload(args.system)
                self.poutput("[  OK  ] Radio IDs reloaded")
            
            elif args.target == 'talkgroups':
                self.poutput("Reloading talkgroups...")
                result = self.tg_mgr.reload(args.system)
                self.poutput("[  OK  ] Talkgroups reloaded")

            elif args.target == 'peer-list':
                result = self.system_api.call('fne-reload-peerlist')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Peer list reloaded")
            
            elif args.target == 'crypto':
                result = self.system_api.call('fne-reload-crypto')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Crypto containers reloaded")
        
        except Exception as e:
            self.perror(f"Error: {e}")
    
    # ========== FNE Commands ==========
    
    fne_parser = argparse.ArgumentParser()
    fne_subparsers = fne_parser.add_subparsers(title='fne commands', dest='fne_cmd')
    
    # fne version
    fne_version_parser = fne_subparsers.add_parser('version', help='Show FNE version')
    
    # fne peerlist
    fne_peerlist_parser = fne_subparsers.add_parser('peer-list', help='List connected peers')
    
    # fne peercount
    fne_peercount_parser = fne_subparsers.add_parser('peer-count', help='Get connected peer count')
    
    # fne tgidlist
    fne_tgidlist_parser = fne_subparsers.add_parser('tgid-list', help='List configured TGIDs')
    
    # fne force-update
    fne_forceupdate_parser = fne_subparsers.add_parser('force-update', help='Force FNE list update')
    
    # fne affiliations
    fne_affs_parser = fne_subparsers.add_parser('affiliations', help='Show affiliated SUs')

    # fne unit-registrations
    fne_unitregs_parser = fne_subparsers.add_parser(
        'unit-registrations',
        aliases=['unit-regs'],
        help='Show registered units'
    )

    # fne grants
    fne_grants_parser = fne_subparsers.add_parser('grants', help='Show active talkgroup grants')
    
    # fne reset-peer
    fne_resetpeer_parser = fne_subparsers.add_parser('reset-peer', help='Reset peer connection')
    fne_resetpeer_parser.add_argument('peer_id', type=int, help='Peer ID')
    
    # fne rid-commit
    fne_ridcommit_parser = fne_subparsers.add_parser('rid-commit', help='Save RID ACL to disk')
    
    # fne tgid-commit
    fne_tgidcommit_parser = fne_subparsers.add_parser('tgid-commit', help='Save TGID ACL to disk')
    
    # fne peer-commit
    fne_peercommit_parser = fne_subparsers.add_parser('peer-commit', help='Save peer ACL to disk')

    # fne reset-total-calls-counter
    fne_resettotalcallscounter_parser = fne_subparsers.add_parser('reset-total-calls-counter', help='Reset total calls counter')

    # fne reset-active-calls-counter
    fne_resetactivecallscounter_parser = fne_subparsers.add_parser('reset-active-calls-counter', help='Reset active calls counter')

    # fne reset-call-collisions-counter
    fne_resetcallcollisionscounter_parser = fne_subparsers.add_parser('reset-call-collisions-counter', help='Reset call collisions counter')
    
    @with_argparser(fne_parser)
    def do_fne(self, args):
        """FNE management commands"""
        if not args.fne_cmd:
            self.do_help('fne')
            return

        # Read-only FNE commands that are safe in non-privileged mode.
        non_privileged_cmds = {
            'peer-list',
            'peer-count',
            'tgid-list',
            'affiliations',
            'unit-registrations',
            'unit-regs',
            'grants',
        }
        if not self.privileged_mode and args.fne_cmd not in non_privileged_cmds:
            self.perror("Command requires privileged mode.")
            return
        
        try:
            if args.fne_cmd == 'version':
                result = self.system_api.call('version')
                if result.get('success'):
                    self._format_version_output(result)
                else:
                    self._display_api_error(result)
            
            elif args.fne_cmd == 'peer-list':
                result = self.system_api.call('fne-peerlist')
                if result.get('success'):
                    self._format_peerlist_output(result)
                else:
                    self._display_api_error(result)
            
            elif args.fne_cmd == 'peer-count':
                result = self.system_api.call('fne-peercount')
                if result.get('success'):
                    self._format_peercount_output(result)
                else:
                    self._display_api_error(result)
            
            elif args.fne_cmd == 'tgid-list':
                result = self.system_api.call('fne-tgidlist')
                if result.get('success'):
                    self._format_tgidlist_output(result)
                else:
                    self._display_api_error(result)
            
            elif args.fne_cmd == 'force-update':
                result = self.system_api.call('fne-force-update')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] FNE list update forced")
            
            elif args.fne_cmd == 'affiliations':
                result = self.system_api.call('fne-affs')
                if result.get('success'):
                    self._format_affiliations_output(result)
                else:
                    self._display_api_error(result)

            elif args.fne_cmd in ('unit-registrations', 'unit-regs'):
                result = self.system_api.call('fne-unitregs')
                if result.get('success'):
                    self._format_unit_regs_output(result)
                else:
                    self._display_api_error(result)

            elif args.fne_cmd == 'grants':
                result = self.system_api.call('fne-grants')
                if result.get('success'):
                    self._format_grants_output(result)
                else:
                    self._display_api_error(result)
            
            elif args.fne_cmd == 'reset-peer':
                result = self.system_api.call('fne-reset-peer', args.peer_id)
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput(f"[  OK  ] Peer {args.peer_id} connection reset")
            
            elif args.fne_cmd == 'rid-commit':
                result = self.system_api.call('fne-rid-commit')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] RID ACL saved to disk")
            
            elif args.fne_cmd == 'tgid-commit':
                result = self.system_api.call('fne-tgid-commit')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] TGID ACL saved to disk")
            
            elif args.fne_cmd == 'peer-commit':
                result = self.system_api.call('fne-peer-commit')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Peer ACL saved to disk")

            elif args.fne_cmd == 'reset-total-calls-counter':
                result = self.system_api.call('fne-reset-total-calls')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Total calls counter reset")

            elif args.fne_cmd == 'reset-active-calls-counter':
                result = self.system_api.call('fne-reset-active-calls')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Active calls counter reset")

            elif args.fne_cmd == 'reset-call-collisions-counter':
                result = self.system_api.call('fne-reset-call-collisions')
                self._display_fne_result(result)
                if result.get('success'):
                    self.poutput("[  OK  ] Call collisions counter reset")
        
        except Exception as e:
            self.perror(f"Error: {e}")
    
    def _format_version_output(self, data: dict):
        """Format version output from JSON response."""
        try:
            version = data.get('version', 'Unknown')
            self.poutput(f"FNE Version: {version}")
        except Exception as e:
            self.poutput(f"Error formatting version output: {e}")
    
    def _format_peercount_output(self, data: dict):
        """Format peer count output from JSON response."""
        try:
            count = data.get('peerCount', 0)
            self.poutput(f"Connected Peers: {count}")
        except Exception as e:
            self.poutput(f"Error formatting peer count output: {e}")
    
    def _format_peerlist_output(self, data: dict):
        """Format peer list output from JSON response.
        
        Args:
            data: JSON response from fne-peerlist command (GET /peer/query API)
        """
        try:
            from rich.table import Table

            peers = data.get('peers', [])
            
            if not peers:
                self.poutput("No peers connected")
                return
            
            # Sort peers by peer ID
            peers.sort(key=lambda x: int(x.get('peerId', 0)))
            
            table = Table(title="Connected Peers")
            table.add_column("Peer ID", style="cyan", no_wrap=True)
            table.add_column("Identity", style="blue")
            table.add_column("Address", style="magenta")
            table.add_column("Port", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Link Peer ID", style="cyan", no_wrap=True)
            table.add_column("Master ID", style="cyan", no_wrap=True)
            table.add_column("Software", style="white")
            table.add_column("SysView", style="bold", no_wrap=True)
            table.add_column("External", style="bold", no_wrap=True)
            table.add_column("Conventional", style="bold", no_wrap=True)
            table.add_column("Console", style="bold", no_wrap=True)
            table.add_column("Voice Ch IDs", style="bold")
            
            for peer in peers:
                peer_id = str(peer.get('peerId', 'N/A'))
                address = peer.get('address', 'N/A')
                port = str(peer.get('port', 'N/A'))
                connected = "Connected" if peer.get('connected', False) else "Disconnected"
                config = peer.get('config', {})
                identity = config.get('identity', 'N/A')
                software = config.get('software', 'N/A')
                parent_peer_id = str(peer.get('parentPeerId', 'N/A'))
                
                # Additional peer flags and configuration
                sysview = "Yes" if config.get('sysView', False) else "No"
                external = "Yes" if config.get('externalPeer', False) else "No"
                master_id = str(config.get('masterPeerId', 'N/A'))
                conventional = "Yes" if config.get('conventionalPeer', False) else "No"
                console = "Yes" if config.get('consolePeer', False) else "No"
                
                # Voice channel peer ID list
                voice_ch_ids = peer.get('voiceChannels', [])
                if voice_ch_ids:
                    if isinstance(voice_ch_ids, list):
                        voice_ch_str = ', '.join(str(id) for id in voice_ch_ids)
                    else:
                        voice_ch_str = str(voice_ch_ids)
                else:
                    voice_ch_str = ''
                
                table.add_row(peer_id, identity, address, port, connected, parent_peer_id, master_id, software,
                             sysview, external, conventional, console, voice_ch_str)
            
            self.poutput(table)
        except Exception as e:
            self.poutput(f"Error formatting peer list output: {e}")
    
    def _format_tgidlist_output(self, data: dict):
        """Format talkgroup list output from JSON response."""
        try:
            from rich.table import Table
            
            tgs = data.get('tgs', [])
            
            if not tgs:
                self.poutput("No talkgroups configured")
                return
            
            table = Table(title="Configured Talkgroups")
            table.add_column("TGID", style="cyan", no_wrap=True)
            table.add_column("Slot", style="green", no_wrap=True)
            table.add_column("Name", style="magenta")
            table.add_column("Alias", style="yellow")
            table.add_column("Active", style="blue")
            table.add_column("Invalid", style="red")
            
            for tg in tgs:
                source = tg.get('source', {})
                tgid = str(source.get('tgid', 'N/A'))
                slot = str(source.get('slot', 'N/A'))
                name = tg.get('name', 'N/A')
                alias = tg.get('alias', 'N/A')
                config = tg.get('config', {})
                active = "Yes" if config.get('active', False) else "No"
                invalid = "Yes" if tg.get('invalid', False) else "No"
                
                table.add_row(tgid, slot, name, alias, active, invalid)
            
            self.poutput(table)
        except Exception as e:
            self.poutput(f"Error formatting talkgroup list output: {e}")
    
    def _format_affiliations_output(self, data: dict):
        """Format affiliations output from JSON response."""
        try:
            from rich.table import Table
            
            affiliations = data.get('affiliations', [])
            
            if not affiliations:
                self.poutput("No active affiliations")
                return
            
            table = Table(title="Active Affiliations")
            table.add_column("Peer ID", style="cyan", no_wrap=True)
            table.add_column("Radio ID", style="magenta", no_wrap=True)
            table.add_column("TGID", style="green", no_wrap=True)
            
            for peer_affs in affiliations:
                peer_id = str(peer_affs.get('peerId', 'N/A'))
                aff_list = peer_affs.get('affiliations', [])
                
                for aff in aff_list:
                    src_id = str(aff.get('srcId', 'N/A'))
                    dst_id = str(aff.get('dstId', 'N/A'))
                    table.add_row(peer_id, src_id, dst_id)
            
            self.poutput(table)
        except Exception as e:
            self.poutput(f"Error formatting affiliations output: {e}")

    def _format_unit_regs_output(self, data: dict):
        """Format registered unit output from JSON response."""
        try:
            from rich.table import Table

            units = data.get('units', [])

            if not units:
                self.poutput("No registered units")
                return

            # The API returns a flat array of unit IDs.
            sorted_units = sorted(units, key=lambda x: int(x))

            table = Table(title="Registered Units")
            table.add_column("Unit ID", style="cyan", no_wrap=True)

            for unit in sorted_units:
                table.add_row(str(unit))

            self.poutput(table)
            total_units = data.get('totalUnits', len(sorted_units))
            self.poutput(f"Total registered units: {total_units}")
        except Exception as e:
            self.poutput(f"Error formatting unit registrations output: {e}")

    def _format_grants_output(self, data: dict):
        """Format grant output from JSON response."""
        try:
            from rich.table import Table

            grants = data.get('grants', [])

            if not grants:
                self.poutput("No active grants")
                return

            sorted_grants = sorted(
                grants,
                key=lambda x: (int(x.get('dstId', 0)), int(x.get('srcId', 0)))
            )

            table = Table(title="Active Talkgroup Grants")
            table.add_column("TGID", style="green", no_wrap=True)
            table.add_column("Source RID", style="magenta", no_wrap=True)
            table.add_column("SSRC", style="cyan", no_wrap=True)

            for grant in sorted_grants:
                dst_id = str(grant.get('dstId', 'N/A'))
                src_id = str(grant.get('srcId', 'N/A'))
                ssrc = str(grant.get('ssrc', 'N/A'))
                table.add_row(dst_id, src_id, ssrc)

            self.poutput(table)
            total_grants = data.get('totalGrants', len(sorted_grants))
            self.poutput(f"Total active grants: {total_grants}")
        except Exception as e:
            self.poutput(f"Error formatting grants output: {e}")
    
    def _format_stats_output(self, data: dict, fne_version: str = 'N/A'):
        """Format FNE statistics output from GET /stats API.
        
        Args:
            data: JSON response from fne-stats command (GET /stats API)
            fne_version: FNE version from version API call
        """
        try:
            from rich.table import Table
            from rich.panel import Panel
            
            # Display basic stats
            self.console.print("\n[bold cyan]FNE Statistics[/bold cyan]")
            
            # General stats section
            stats_info = []
            stats_info.append(f"Version: {fne_version}")
            
            stats_info.append(f"Total Calls Processed: {data.get('totalCallsProcessed', 'N/A')}")
            stats_info.append(f"Total Call Collisions: {data.get('totalCallCollisions', 'N/A')}")
            stats_info.append(f"Active Calls: {data.get('totalActiveCalls', 'N/A')}")

            # Table entry counts
            stats_info.append(f"\n[bold]Table Entries:[/bold]")
            stats_info.append(f"  Talkgroup Entries: {data.get('tgTotalEntries', 0)}")
            stats_info.append(f"  Radio ID Entries: {data.get('ridTotalEntries', 0)}")
            stats_info.append(f"  Peer Entries: {data.get('peerListTotalEntries', 0)}")
            stats_info.append(f"  Adjacent Site Map Entries: {data.get('adjSiteMapTotalEntries', 0)}")
            stats_info.append(f"  Crypto Key Entries: {data.get('cryptoKeyTotalEntries', 0)}")

            # Table load times
            stats_info.append(f"\n[bold]Table Last Load Times:[/bold]")

            table_last = data.get('tableLastLoad', {})

            rid_last = table_last.get('ridLastLoadTime', 'N/A')
            tg_last = table_last.get('tgLastLoadTime', 'N/A')
            peer_last = table_last.get('peerListLastLoadTime', 'N/A')
            crypto_last = table_last.get('cryptoKeyLastLoadTime', 'N/A')
            adj_site_last = table_last.get('adjSiteMapLastLoadTime', 'N/A')

            stats_info.append(f"  Talkgroup Rules: {tg_last}")
            stats_info.append(f"  Radio IDs: {rid_last}")
            stats_info.append(f"  Peer List: {peer_last}")
            stats_info.append(f"  Crypto Keys: {crypto_last}")
            stats_info.append(f"  Adjacent Site Map: {adj_site_last}")
                        
            # Display general info
            self.console.print('\n'.join(stats_info))
            
            # Peer statistics table
            peer_stats = data.get('peerStats', [])
            if peer_stats:
                self.console.print("\n[bold cyan]Peer Statistics[/bold cyan]")
                
                # Sort peers by peer ID
                peer_stats.sort(key=lambda x: int(x.get('peerId', 0)))
                
                peer_table = Table(title="Connected Peers Stats")
                peer_table.add_column("Peer ID", style="cyan", no_wrap=True)
                peer_table.add_column("Master ID", style="blue", no_wrap=True)
                peer_table.add_column("Address", style="magenta")
                peer_table.add_column("Port", style="green", no_wrap=True)
                peer_table.add_column("Last Ping", style="yellow")
                peer_table.add_column("Pings Rx", style="white", no_wrap=True)
                peer_table.add_column("Missed Updates", style="red", no_wrap=True)
                
                for peer in peer_stats:
                    peer_id = str(peer.get('peerId', 'N/A'))
                    master_id = str(peer.get('masterId', 'N/A'))
                    address = peer.get('address', 'N/A')
                    port = str(peer.get('port', 'N/A'))
                    last_ping = peer.get('lastPing', 'N/A')
                    pings_rx = str(peer.get('pingsReceived', 0))
                    missed_updates = str(peer.get('missedMetadataUpdates', 0))
                    
                    peer_table.add_row(peer_id, master_id, address, port, last_ping, pings_rx, missed_updates)
                
                self.poutput(peer_table)
            
        except Exception as e:
            self.poutput(f"Error formatting statistics output: {e}")
    
    def _format_spanning_tree_output(self, data: dict):
        """Format spanning tree topology output from GET /spanning-tree API.
        
        Args:
            data: JSON response from fne-spanning-tree command (GET /spanning-tree API)
        """
        try:
            master_tree = data.get('masterTree', [])
            
            if not master_tree:
                self.poutput("No spanning tree information available")
                return
            
            self.console.print("\n[bold cyan]Network Spanning Tree Topology[/bold cyan]")
            
            # Recursively display the tree structure
            for root_node in master_tree:
                self._print_tree_node(root_node, indent=0)
        
        except Exception as e:
            self.poutput(f"Error formatting spanning tree output: {e}")
    
    def _print_tree_node(self, node: dict, indent: int = 0):
        """Recursively print tree node with proper indentation.
        
        Args:
            node: Tree node dictionary with id, masterId, identity, and children
            indent: Current indentation level for hierarchical display
        """
        # Format node information
        node_id = node.get('id', 'N/A')
        master_id = node.get('masterId', 'N/A')
        identity = node.get('identity', 'N/A')
        
        # Create indentation prefix
        prefix = "  " * indent
        connector = "├─ " if indent > 0 else ""
        
        # Print node
        self.poutput(f"{prefix}{connector}Peer ID {node_id}, Master Peer ID {master_id} ({identity})")
        
        # Process children recursively - sort by peer ID first
        children = node.get('children', [])
        sorted_children = sorted(children, key=lambda x: int(x.get('id', 0)))
        for i, child in enumerate(sorted_children):
            is_last = (i == len(sorted_children) - 1)
            # Adjust indent for child display
            self._print_tree_node(child, indent=indent + 1)
    
    def _display_fne_result(self, result: dict, format_json: bool = False):
        """Display FNE command result."""
        if result.get('success'):
            if format_json:
                # Pretty print JSON result
                try:
                    import json
                    self.poutput(json.dumps(result, indent=2))
                except:
                    self.poutput(str(result))
            elif result.get('output'):
                # Display output field if present
                self.poutput(result.get('output'))
        else:
            self._display_api_error(result)
    
    def _display_api_error(self, result: dict):
        """Display API error with detailed information."""
        error_msg = result.get('error', 'Unknown error')
        returncode = result.get('returncode', 'N/A')
        command = result.get('command', 'unknown')
        
        # Build error message with diagnostics
        msg_parts = [f"Error: {error_msg}"]
        
        # Add return code if available
        if returncode and returncode != 'N/A' and returncode != -1:
            msg_parts.append(f"(return code: {returncode})")
        
        # Add connection info for connection errors
        if ('connection' in error_msg.lower() or 'refused' in error_msg.lower() or 
            'timeout' in error_msg.lower()):
            host = result.get('host')
            port = result.get('port')
            if host and port:
                msg_parts.append(f"(attempting {host}:{port})")
        
        self.perror(" ".join(msg_parts))
    
    # ========== Peer Commands ==========
    
    peer_parser = argparse.ArgumentParser()
    peer_subparsers = peer_parser.add_subparsers(title='peer commands', dest='peer_cmd')
    
    # peer add
    add_peer_parser = peer_subparsers.add_parser('add', help='Add peer')
    add_peer_parser.add_argument('peer_id', type=int, help='Peer ID')
    add_peer_parser.add_argument('password', help='Peer password')
    add_peer_parser.add_argument('--name', help='Peer name/description')
    add_peer_parser.add_argument('--replica', type=int, choices=[0, 1], default=0, help='Replica flag (0 or 1)')
    add_peer_parser.add_argument('--require-key', type=int, choices=[0, 1], default=0, help='Require encryption key')
    add_peer_parser.add_argument('--can-inhibit', type=int, choices=[0, 1], default=0, help='Can inhibit flag')

    
    # peer remove
    remove_peer_parser = peer_subparsers.add_parser('remove', help='Remove peer')
    remove_peer_parser.add_argument('peer_id', type=int, help='Peer ID')
    
    # peer enable
    enable_peer_parser = peer_subparsers.add_parser('enable', help='Enable peer')
    enable_peer_parser.add_argument('peer_id', type=int, help='Peer ID')
    
    # peer disable
    disable_peer_parser = peer_subparsers.add_parser('disable', help='Disable peer')
    disable_peer_parser.add_argument('peer_id', type=int, help='Peer ID')
    
    # peer edit
    edit_peer_parser = peer_subparsers.add_parser('edit', help='Edit peers interactively')
    
    @with_argparser(peer_parser)
    def do_peer(self, args):
        """Peer connection management"""
        if not self._check_feature_available('peer'):
            self._subprime_unavailable()
            return
        
        if not self.privileged_mode:
            self.perror("Command requires privileged mode.")
            return
        
        if not args.peer_cmd:
            self.do_help('peer')
            return
        
        try:
            if args.peer_cmd == 'add':
                success, message = self.peer_mgr.add_peer(
                    'system',
                    args.peer_id,
                    args.password,
                    replica=args.replica,
                    peer_name=args.name or "",
                    require_key=args.require_key,
                    can_inhibit=args.can_inhibit
                )
                if success:
                    self.poutput(f"[  OK  ] {message}")
                else:
                    self.perror(f"[FAILED] {message}")
            
            elif args.peer_cmd == 'remove':
                success, message = self.peer_mgr.remove_peer('system', args.peer_id)
                if success:
                    self.poutput(f"[  OK  ] {message}")
                else:
                    self.perror(f"[FAILED] {message}")
            
            elif args.peer_cmd == 'enable':
                success, message = self.peer_mgr.enable_peer('system', args.peer_id)
                if success:
                    self.poutput(f"[  OK  ] {message}")
                else:
                    self.perror(f"[FAILED] {message}")
            
            elif args.peer_cmd == 'disable':
                success, message = self.peer_mgr.disable_peer('system', args.peer_id)
                if success:
                    self.poutput(f"[  OK  ] {message}")
                else:
                    self.perror(f"[FAILED] {message}")
            
            elif args.peer_cmd == 'edit':
                success, message = self.peer_mgr.edit_peers_interactive('system')
                if success:
                    self.poutput(f"[  OK  ] {message}")
                else:
                    self.perror(f"[FAILED] {message}")
        
        except Exception as e:
            self.perror(f"Error: {e}")
    
    # ========== TUI Command ==========
    
    def do_tui(self, _):
        """Launch the TUI interface"""
        self.poutput("\nLaunching TUI...")
        sys.exit(20)  # Special exit code for TUI launch
    
    # ========== Exit Commands ==========
    
    def do_exit(self, _):
        """Exit the CLI"""
        self.poutput("\nExiting DVM Management CLI. Goodbye!")
        return True
    
    def do_quit(self, args):
        """Exit the CLI (alias for exit)"""
        return self.do_exit(args)
    
    def do_EOF(self, _):
        """Exit on EOF (Ctrl-D)"""
        self.poutput("")
        return self.do_exit(_)


def main(config_file: Optional[Path] = None, command: Optional[str] = None) -> int:
    """
    Main entry point for CLI.
    
    Args:
        config_file: Optional configuration file path
        command: Optional command to execute (non-interactive mode)
    
    Returns:
        Exit code
    """
    try:
        # Load configuration
        if config_file is None:
            config_file = Path('/opt/console.conf')
        
        config = ConsoleConfig.load(config_file)
        
        # If command provided, execute it and exit (non-interactive mode)
        if command:
            cli = DVMMgmtCLI(config)
            try:
                # Split compound commands by semicolon or parse as sequence
                # First check if there are semicolons (explicit command separator)
                if ';' in command:
                    commands = [cmd.strip() for cmd in command.split(';')]
                else:
                    # Check for compound commands like "enable reload service brbnd"
                    # Parse to handle enable/configure followed by another command
                    parts = command.strip().split(None, 1)
                    if len(parts) == 2 and parts[0] in ('enable', 'en', 'configure', 'conf'):
                        # Execute enable/configure first, then the rest
                        commands = [parts[0], parts[1]]
                    else:
                        # Single command
                        commands = [command]
                
                # Execute each command in sequence
                for cmd in commands:
                    if cmd:  # Skip empty commands
                        cli.onecmd(cmd)
                
                return 0
            except Exception as e:
                print(f"Error executing command: {e}")
                return 1
        
        # Interactive mode
        while True:
            # Start CLI
            cli = DVMMgmtCLI(config)
            
            # Print intro banner directly before cmdloop
            intro_text = """
╔═══════════════════════════════════════════════════════════════════════╗
║         DVM Management Console                                        ║
║         Copyright (C) 2026 DVMProject Authors                         ║
╚═══════════════════════════════════════════════════════════════════════╝

Type 'help' or '?' to list commands.
Type 'enable' to enter privileged mode.
Type 'exit' or 'quit' to exit.
"""
            print(intro_text)
            
            # Display hostname
            hostname = socket.gethostname()
            print(f"Hostname: {hostname}")
            
            # Display system log prefix
            log_prefix = config.log_prefix_system if config.log_prefix_system else "N/A"
            print(f"System Prefix: {log_prefix}\n")
            
            sys.stdout.flush()  # Force flush to ensure it displays
            
            try:
                cli.cmdloop()
                # Normal exit
                return 0
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 0
            except KeyboardInterrupt:
                # User interrupted (Ctrl+C)
                print("\nUse 'exit' or 'quit' to exit the CLI.")
                continue
    
    except KeyboardInterrupt:
        print("\n\nInterrupted. Exiting...")
        return 130
    
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
