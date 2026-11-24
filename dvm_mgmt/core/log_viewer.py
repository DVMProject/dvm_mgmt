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
Live log viewing with colorization.
"""

import subprocess
import sys
import os
import re
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional
import glob


class LogColorizer:
    """Handles log colorization using ANSI escape codes."""
    
    @staticmethod
    def colorize_fne(line: str) -> str:
        """
        Colorize FNE log line.
        """
        # Clear ID: "ID: " -> "ID "
        line = re.sub(r'ID: ', 'ID ', line)
        
        # Log levels
        line = re.sub(r'\bW:', '\033[1m\033[33mW:\033[0m', line)
        line = re.sub(r'\bE:', '\033[1m\033[31mE:\033[0m', line)
        line = re.sub(r'\bM:', 'M:', line)
        line = re.sub(r'\bI:', 'I:', line)
        line = re.sub(r'\bD:', '\033[1m\033[34mD:\033[0m', line)
        line = re.sub(r'\bU:', '\033[1m\033[32mU:\033[0m', line)
        
        # NAK - bold red
        line = re.sub(r'NAK', '\033[0m\033[1m\033[31mNAK\033[0m', line)
        
        # HOST - bold white
        line = re.sub(r'\(HOST\)', '\033[1m\033[37m(HOST)\033[0m', line)
        
        # RF - bold blue
        line = re.sub(r'\(RF\)', '\033[1m\033[34m(RF)\033[0m', line)
        
        # NET - bold cyan
        line = re.sub(r'\(NET\)', '\033[1m\033[36m(NET)\033[0m', line)
        
        # MASTER - bold blue
        line = re.sub(r'\(MSTR\)', '\033[1m\033[34m(MSTR)\033[0m', line)
        
        # PEER - bold cyan
        line = re.sub(r'\(PEER\)', '\033[1m\033[36m(PEER)\033[0m', line)
        
        # STP - bold green
        line = re.sub(r'\(STP\)', '\033[1m\033[32m(STP)\033[0m', line)
        
        # REPL - bold yellow
        line = re.sub(r'\(REPL\)', '\033[1m\033[33m(REPL)\033[0m', line)
        
        # DMR colors
        line = re.sub(r'VOICE', '\033[36mVOICE', line)
        line = re.sub(r'TERMINATOR_WITH_LC', '\033[0m\033[32mTERMINATOR_WITH_LC', line)
        line = re.sub(r'CSBK', '\033[0m\033[95mCSBK', line)
        
        # P25 colors
        line = re.sub(r'LDU', '\033[36mLDU', line)
        line = re.sub(r'TDU', '\033[0m\033[32mTDU', line)
        line = re.sub(r'HDU', '\033[0m\033[32mHDU', line)
        line = re.sub(r'TSDU', '\033[0m\033[35mTSDU', line)
        
        # NXDN colors
        line = re.sub(r'VCALL', '\033[36mVCALL', line)
        line = re.sub(r'TX_REL', '\033[0m\033[32mTX_REL', line)
        
        # Affiliation colors
        line = re.sub(r'Affiliations', '\033[1m\033[36mAffiliations', line)
        line = re.sub(r'Affiliation', '\033[1m\033[36mAffiliation', line)
        
        # End of line clear
        line = line + '\033[0m'
        
        return line


def view_syslog_fne(netsplit: bool = False,
                    duplicates: bool = False, unauthorized: bool = False, scrollback: int = 5000, tail: bool = False,
                    grep_pattern: Optional[str] = None,
                    log_file: Optional[str] = None, log_prefix_system: Optional[str] = None) -> None:
    """
    View FNE logs from syslog with colorization.
    
    Args:
        netsplit: Show only netsplit messages
        duplicates: Show only duplicate messages
        unauthorized: Show only unauthorized messages
        scrollback: Number of lines to show
        tail: If True, use tail -f for live following
        grep_pattern: Optional extended regular expression used to filter matching log lines
        log_file: Log file path (defaults to /var/log/syslog if not provided)
        log_prefix_system: System log prefix (defaults to SKYN-FNE1-CR1 if not provided)
    """
    # Use configuration values or defaults
    if log_file is None:
        log_file = "/var/log/syslog"
    if log_prefix_system is None:
        log_prefix_system = "SKYN-FNE1-CR1"
    
    colorizer = LogColorizer()
    processes = []  # Track all processes for cleanup
    
    try:
        if netsplit:
            # Static grep for netsplit messages
            grep1 = subprocess.Popen(["sudo", "grep", "-E", "--", log_prefix_system, log_file],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            grep2 = subprocess.Popen(["grep", "-E", "netsplit"],
                                    stdin=grep1.stdout, stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE, text=True)
            grep1.stdout.close()
            processes.extend([grep1, grep2])
            
            for line in grep2.stdout:
                print(colorizer.colorize_fne(line.rstrip()))
            grep2.wait()
            
        elif duplicates:
            # Static grep for duplicate messages
            grep1 = subprocess.Popen(["sudo", "grep", "-E", "--", log_prefix_system, log_file],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            grep2 = subprocess.Popen(["grep", "-E", "duplicate"],
                                    stdin=grep1.stdout, stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE, text=True)
            grep1.stdout.close()
            processes.extend([grep1, grep2])
            
            for line in grep2.stdout:
                print(colorizer.colorize_fne(line.rstrip()))
            grep2.wait()

        elif unauthorized:
            # Static grep for unauthorized messages
            grep1 = subprocess.Popen(["sudo", "grep", "-E", "--", log_prefix_system, log_file],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            grep2 = subprocess.Popen(["grep", "-E", "unauthorized"],
                                    stdin=grep1.stdout, stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE, text=True)
            grep1.stdout.close()
            processes.extend([grep1, grep2])
            
            for line in grep2.stdout:
                print(colorizer.colorize_fne(line.rstrip()))
            grep2.wait()

        else:
            # Live tail with follow (or static display)
            pattern = log_prefix_system
            
            if grep_pattern and not tail:
                # A static filtered search examines the complete log rather than
                # only the final scrollback window.
                grep_proc = subprocess.Popen(
                    ["sudo", "grep", "-aE", "--", pattern, log_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None,
                )
                processes.append(grep_proc)
            else:
                tail_args = ["sudo", "tail", "-n", str(scrollback)]
                if tail:
                    tail_args.append("-f")
                tail_args.append(log_file)

                tail_proc = subprocess.Popen(
                    tail_args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None,
                )
                prefix_filter_args = ["grep", "-E"]
                if tail:
                    prefix_filter_args.append("--line-buffered")
                prefix_filter_args.extend(["--", pattern])
                grep_proc = subprocess.Popen(
                    prefix_filter_args,
                    stdin=tail_proc.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None,
                )
                tail_proc.stdout.close()
                processes.extend([tail_proc, grep_proc])

            output_proc = grep_proc
            if grep_pattern:
                filter_args = ["grep", "-aiE"]
                if tail:
                    filter_args.append("--line-buffered")
                filter_args.extend(["--", grep_pattern])
                filter_proc = subprocess.Popen(
                    filter_args,
                    stdin=grep_proc.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None,
                )
                grep_proc.stdout.close()
                processes.append(filter_proc)
                output_proc = filter_proc
            
            # Print header for static display (non-tail mode)
            if not tail:
                if grep_pattern:
                    print(f"\n--- SYSTEM Log (matching {grep_pattern!r}) ---\n")
                else:
                    print(f"\n--- SYSTEM Log (last {scrollback} lines) ---\n")
            
            # Read and colorize output line by line
            for line in output_proc.stdout:
                print(colorizer.colorize_fne(line.rstrip()))

            for proc in reversed(processes):
                proc.wait()
            
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - terminate all subprocesses
        for proc in processes:
            try:
                # Try to kill process group first (for tail -f and grep)
                if hasattr(proc, 'pid'):
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, AttributeError):
                        # Fall back to regular terminate if process group kill fails
                        proc.terminate()
            except:
                pass
        # Wait for all processes to terminate
        for proc in processes:
            try:
                proc.wait(timeout=0.5)
            except:
                # Force kill if doesn't terminate quickly
                try:
                    if hasattr(proc, 'pid'):
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except:
                            proc.kill()
                    else:
                        proc.kill()
                    proc.wait()
                except:
                    pass
    except Exception as e:
        # Clean up processes on error
        for proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except:
                try:
                    proc.kill()
                except:
                    pass
        print(f"Error viewing log: {e}", file=sys.stderr)


def view_log_file(log_pattern: str, colorize_func, grep_pattern: Optional[str] = None,
                  lines: int = 1000, tail_follow: bool = False) -> int:
    """
    View a log file with colorization and optional grep filtering.
    
    Args:
        log_pattern: Glob pattern for log file (with today's date or absolute path)
        colorize_func: Function to colorize each line
        grep_pattern: Optional grep pattern to filter lines
        lines: Number of lines to tail
        tail_follow: If True, use tail -f for live following; if False, show static content
        
    Returns:
        Number of lines displayed (0 if no matches found)
    """
    colorizer = LogColorizer()
    today = datetime.now().strftime('%Y-%m-%d')
    pattern = log_pattern.replace('YYYY-MM-DD', today)
    
    # Expand pattern and find matching files
    log_files = glob.glob(pattern)
    
    if not log_files:
        # Try alternative patterns and provide helpful diagnostics
        print(f"Log file not found: {pattern}", file=sys.stderr)
        
        # Check if directory exists
        pattern_dir = pattern.rsplit('/', 1)[0] if '/' in pattern else '.'
        if os.path.isdir(pattern_dir):
            try:
                available_files = os.listdir(pattern_dir)
                if available_files:
                    print(f"\nAvailable files in {pattern_dir}:", file=sys.stderr)
                    for f in sorted(available_files)[:10]:  # Show first 10
                        print(f"  {f}", file=sys.stderr)
                else:
                    print(f"No files found in {pattern_dir}", file=sys.stderr)
            except Exception as e:
                print(f"Error reading directory {pattern_dir}: {e}", file=sys.stderr)
        else:
            print(f"Directory not found: {pattern_dir}", file=sys.stderr)
        return 0
    
    # Use the most recent file if multiple matches
    log_file = sorted(log_files)[-1]
    processes = []
    line_count = 0
    
    try:
        # Build tail command with or without -f flag
        tail_args = ["tail", "-n", str(lines)]
        if tail_follow:
            tail_args.append("-f")
        tail_args.append(log_file)
        
        if grep_pattern:
            # Tail with grep filter
            tail = subprocess.Popen(tail_args,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None)
            grep = subprocess.Popen(["grep", "-aE", grep_pattern],
                                   stdin=tail.stdout, stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE, text=True,
                                   preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None)
            tail.stdout.close()
            processes.extend([tail, grep])
            
            for line in grep.stdout:
                print(colorize_func(line.rstrip()))
                line_count += 1
                
            grep.wait()
            tail.wait()
        else:
            # Just tail without grep
            tail = subprocess.Popen(tail_args,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None)
            processes.append(tail)
            
            for line in tail.stdout:
                print(colorize_func(line.rstrip()))
                line_count += 1
                
            tail.wait()
        
        return line_count
            
    except KeyboardInterrupt:
        # Clean up processes on Ctrl+C
        for proc in processes:
            try:
                if hasattr(proc, 'pid'):
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, AttributeError):
                        proc.terminate()
            except:
                pass
        for proc in processes:
            try:
                proc.wait(timeout=0.5)
            except:
                try:
                    if hasattr(proc, 'pid'):
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except:
                            proc.kill()
                    else:
                        proc.kill()
                    proc.wait()
                except:
                    pass
        return line_count
    except Exception as e:
        print(f"Error viewing log: {e}", file=sys.stderr)
        return line_count
