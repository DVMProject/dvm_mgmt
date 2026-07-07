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
Process Management for DVM Services
"""

import psutil
import subprocess
import signal
import time
from typing import List, Optional, Dict, Any
from enum import Enum


class ServiceState(Enum):
    """Service state enumeration."""
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class ProcessManager:
    """Manager for DVM service processes."""
    
    SERVICES = {
        'fne': 'dvmfne',
        'sysview': 'sysview',
    }
    
    def __init__(self):
        """Initialize process manager."""
        pass

    def is_service_supported(self, service: str) -> bool:
        """Check whether a service key is supported for management."""
        return service in self.SERVICES
    
    def get_pid(self, service: str) -> Optional[int]:
        """
        Get PID of a service (returns first instance if multiple are running).
        
        Args:
            service: Service name (las, rc, fne)
        
        Returns:
            PID if running, None otherwise
        """
        process_name = self.SERVICES.get(service)
        if not process_name:
            return None
        
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == process_name:
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return None
    
    def get_all_pids(self, service: str) -> List[int]:
        """
        Get all PIDs of a service (handles multiple instances).
        
        Args:
            service: Service name (las, rc, fne)
        
        Returns:
            List of PIDs (empty if none running)
        """
        process_name = self.SERVICES.get(service)
        if not process_name:
            return []
        
        pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == process_name:
                    pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return pids
    
    def get_state(self, service: str) -> ServiceState:
        """
        Get service state.
        
        Args:
            service: Service name
        
        Returns:
            Service state
        """
        pid = self.get_pid(service)
        if pid:
            return ServiceState.RUNNING
        return ServiceState.STOPPED
    
    def is_running(self, service: str) -> bool:
        """Check if service is running."""
        return self.get_pid(service) is not None
    
    def stop_service(self, service: str, force: bool = False) -> bool:
        """
        Stop a service (stops all matching processes).
        
        Args:
            service: Service name
            force: Use SIGKILL if SIGTERM fails
        
        Returns:
            True if all processes stopped successfully
        """
        pids = self.get_all_pids(service)
        if not pids:
            return True  # Already stopped
        
        all_stopped = True
        for pid in pids:
            try:
                # Try graceful shutdown first
                process = psutil.Process(pid)
                process.send_signal(signal.SIGTERM)
                
                # Wait up to 2 seconds
                try:
                    process.wait(timeout=2)
                except psutil.TimeoutExpired:
                    if force:
                        # Force kill
                        process.send_signal(signal.SIGKILL)
                        time.sleep(0.5)
                        if process.is_running():
                            all_stopped = False
                    else:
                        all_stopped = False
            
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue  # Process already gone or no access
        
        return all_stopped
    
    def restart_service(self, service: str) -> bool:
        """
        Restart a service.
        
        Args:
            service: Service name (or composite service like 'brbnd')
        
        Returns:
            True if restarted successfully
        """
        if not self.is_service_supported(service):
            return False
        
        # Stop the service
        self.stop_service(service, force=True)
        
        # Note: Starting would require systemd integration or service scripts
        # For now, just return True if stopped
        time.sleep(5)
        return not self.is_running(service)
    
    def get_all_services(self) -> Dict[str, Dict[str, Any]]:
        """
        Get status of all services.

        Returns:
            Dictionary with service status information (handles multiple instances)
        """
        services = {}

        # Pass 1: collect process info and prime cpu_percent counters.
        # psutil.cpu_percent(interval=None) always returns 0.0 on the first
        # call for a given Process object — it needs two measurements to
        # calculate a delta.  We keep the Process objects so we can read the
        # real value after a short sleep.
        _procs: Dict[str, list] = {}  # service_key -> [(instance_info, Process|None)]

        for service_key, process_name in self.SERVICES.items():
            pids = self.get_all_pids(service_key)
            state = ServiceState.RUNNING if pids else ServiceState.STOPPED

            instances = []
            proc_pairs = []
            for pid in pids:
                instance_info: Dict[str, Any] = {'pid': pid}
                proc_obj = None
                try:
                    proc_obj = psutil.Process(pid)
                    proc_obj.cpu_percent(interval=None)  # prime — always 0.0
                    instance_info['memory_mb'] = proc_obj.memory_info().rss / 1024 / 1024
                    instance_info['create_time'] = proc_obj.create_time()
                    instance_info['cmdline'] = ' '.join(proc_obj.cmdline())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_obj = None
                instances.append(instance_info)
                proc_pairs.append((instance_info, proc_obj))

            _procs[service_key] = proc_pairs

            info: Dict[str, Any] = {
                'name': process_name,
                'state': state.value,
                'count': len(pids),
                'instances': instances,
                'pid': pids[0] if pids else None,
            }
            services[service_key] = info

        # Brief pause so the second cpu_percent call returns a real value.
        time.sleep(0.2)

        # Pass 2: read actual CPU percentages.
        for service_key, proc_pairs in _procs.items():
            for instance_info, proc_obj in proc_pairs:
                if proc_obj is None:
                    instance_info.setdefault('cpu_percent', 0.0)
                    continue
                try:
                    instance_info['cpu_percent'] = proc_obj.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    instance_info.setdefault('cpu_percent', 0.0)

        return services

