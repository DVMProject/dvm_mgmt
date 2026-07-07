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
Peer management operations.

Peer ACL File Format (CSV):
peer_id,password,replica,peer_name,request_key,can_inhibit,call_priority,jitter,max_size,max_wait

Example:
1001,MyPassword,0,Site1,0,0,0,360,12582912,25
1002,OtherPass,1,Site2Replica,1,1,0,360,12582912,25
"""

import subprocess
import csv
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

try:
    from dvm_mgmt.core.config import ConsoleConfig
except ImportError:
    ConsoleConfig = None


@dataclass
class Peer:
    """Represents a peer entry in the ACL file."""

    peer_id: int
    password: str
    replica: int = 0
    peer_name: str = ""
    request_key: int = 0
    can_inhibit: int = 0
    call_priority: int = 0
    jitter: int = 360
    max_size: int = 12582912
    max_wait: int = 25


class PeerManager:
    """Manages peer connections via CSV ACL files."""

    def __init__(
        self,
        config: Optional["ConsoleConfig"] = None,
        system_peer_file: Optional[str] = None,
        public_peer_file: Optional[str] = None,
        peered_path: Optional[str] = None,
    ):
        """
        Initialize peer manager.

        Args:
            config: Console configuration (optional)
            system_peer_file: Path to system peer list CSV (optional, overrides config)
            public_peer_file: Path to public peer list CSV (optional, overrides config)
            peered_path: Path to peered binary (optional, overrides config)
        """
        # Load configuration or use defaults
        self.config = config if config else (ConsoleConfig() if ConsoleConfig else None)

        # Set peer file paths from config or parameters
        if system_peer_file:
            self.system_peer_file = Path(system_peer_file)
        elif self.config and hasattr(self.config, "system_peerid_acl_file"):
            self.system_peer_file = self.config.system_peerid_acl_file
        else:
            self.system_peer_file = Path("/opt/dvm/peer_list.dat")

        if public_peer_file:
            self.public_peer_file = Path(public_peer_file)
        elif self.config and hasattr(self.config, "public_peerid_acl_file"):
            self.public_peer_file = self.config.public_peerid_acl_file
        else:
            self.public_peer_file = Path("/opt/dvm/peer_list.public.dat")

        # Set peered binary path
        if peered_path:
            self.peered_path = Path(peered_path)
        elif self.config and hasattr(self.config, "peered_path"):
            self.peered_path = self.config.peered_path
        else:
            self.peered_path = Path("/opt/dvm/bin/peered")

    def _get_peer_file(self, system: str) -> Path:
        """Get the appropriate peer file path."""
        if system == "system":
            return self.system_peer_file
        elif system == "public":
            return self.public_peer_file
        else:
            raise ValueError(f"Invalid system type: {system}")

    def _read_peers(self, peer_file: Path) -> List[Peer]:
        """
        Read peers from CSV file.

        Args:
            peer_file: Path to peer CSV file

        Returns:
            List of Peer objects
        """
        peers = []

        if not peer_file.exists():
            return peers

        try:
            with open(peer_file, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    # Skip empty lines or comments
                    if not row or not row[0].strip() or row[0].strip().startswith("#"):
                        continue

                    # Parse peer entry
                    # Format: peer_id,password,replica,peer_name,req_key,can_inh,call_pri,jitter,max_size,max_wait
                    peer = Peer(
                        peer_id=int(row[0]) if row[0] else 0,
                        password=row[1] if len(row) > 1 else "",
                        replica=int(row[2]) if len(row) > 2 and row[2] else 0,
                        peer_name=row[3] if len(row) > 3 else "",
                        request_key=int(row[4]) if len(row) > 4 and row[4] else 0,
                        can_inhibit=int(row[5]) if len(row) > 5 and row[5] else 0,
                        call_priority=int(row[6]) if len(row) > 6 and row[6] else 0,
                        jitter=int(row[7]) if len(row) > 7 and row[7] else 360,
                        max_size=int(row[8]) if len(row) > 8 and row[8] else 12582912,
                        max_wait=int(row[9]) if len(row) > 9 and row[9] else 25,
                    )
                    peers.append(peer)

        except Exception as e:
            raise RuntimeError(f"Error reading peer file {peer_file}: {e}")

        return peers

    def _write_peers(self, peer_file: Path, peers: List[Peer]) -> None:
        """
        Write peers to CSV file.

        Args:
            peer_file: Path to peer CSV file
            peers: List of Peer objects
        """
        try:
            # Ensure directory exists
            peer_file.parent.mkdir(parents=True, exist_ok=True)

            with open(peer_file, "w", newline="") as f:
                writer = csv.writer(f)
                for peer in peers:
                    writer.writerow(
                        [
                            peer.peer_id,
                            peer.password,
                            peer.replica,
                            peer.peer_name,
                            peer.request_key,
                            peer.can_inhibit,
                            peer.call_priority,
                            peer.jitter,
                            peer.max_size,
                            peer.max_wait,
                        ]
                    )

        except Exception as e:
            raise RuntimeError(f"Error writing peer file {peer_file}: {e}")

    def list_peers(self, system: str = "system") -> List[Dict]:
        """
        List all peers.

        Args:
            system: System type ('system' or 'public')

        Returns:
            List of peer dictionaries
        """
        peer_file = self._get_peer_file(system)
        peers = self._read_peers(peer_file)

        return [
            {
                "id": p.peer_id,
                "password": p.password,
                "replica": p.replica,
                "name": p.peer_name,
                "request_key": p.request_key,
                "can_inhibit": p.can_inhibit,
                "call_priority": p.call_priority,
                "jitter": p.jitter,
                "max_size": p.max_size,
                "max_wait": p.max_wait,
                "enabled": True,  # CSV format doesn't have enabled field - all entries are enabled
            }
            for p in peers
        ]

    def add_peer(
        self,
        system: str,
        peer_id: int,
        password: str,
        replica: int = 0,
        peer_name: str = "",
        request_key: int = 0,
        can_inhibit: int = 0,
        call_priority: int = 0,
        jitter: int = 360,
        max_size: int = 12582912,
        max_wait: int = 25,
    ) -> Tuple[bool, str]:
        """
        Add a new peer.

        Args:
            system: System type ('system' or 'public')
            peer_id: Peer ID
            password: Peer password
            replica: Replica flag (0 or 1)
            peer_name: Peer name/description
            request_key: Request encryption key flag
            can_inhibit: Can inhibit flag
            call_priority: Call priority
            jitter: Jitter buffer size
            max_size: Maximum packet size
            max_wait: Maximum wait time

        Returns:
            Tuple of (success, message)
        """
        try:
            peer_file = self._get_peer_file(system)
            peers = self._read_peers(peer_file)

            # Check if peer already exists
            for peer in peers:
                if peer.peer_id == peer_id:
                    return False, f"Peer {peer_id} already exists"

            # Add new peer
            new_peer = Peer(
                peer_id=peer_id,
                password=password,
                replica=replica,
                peer_name=peer_name,
                request_key=request_key,
                can_inhibit=can_inhibit,
                call_priority=call_priority,
                jitter=jitter,
                max_size=max_size,
                max_wait=max_wait,
            )
            peers.append(new_peer)

            # Write back
            self._write_peers(peer_file, peers)

            return True, f"Added peer {peer_id}"

        except Exception as e:
            return False, str(e)

    def remove_peer(self, system: str, peer_id: int) -> Tuple[bool, str]:
        """
        Remove a peer.

        Args:
            system: System type ('system' or 'public')
            peer_id: Peer ID to remove

        Returns:
            Tuple of (success, message)
        """
        try:
            peer_file = self._get_peer_file(system)
            peers = self._read_peers(peer_file)

            # Filter out the peer
            original_count = len(peers)
            peers = [p for p in peers if p.peer_id != peer_id]

            if len(peers) == original_count:
                return False, f"Peer {peer_id} not found"

            # Write back
            self._write_peers(peer_file, peers)

            return True, f"Removed peer {peer_id}"

        except Exception as e:
            return False, str(e)

    def enable_peer(self, system: str, peer_id: int) -> Tuple[bool, str]:
        """
        Enable a peer (no-op for CSV format - peers are always enabled if present).

        Args:
            system: System type ('system' or 'public')
            peer_id: Peer ID

        Returns:
            Tuple of (success, message)
        """
        # CSV format doesn't have enabled/disabled state
        # This is a no-op for compatibility with CLI interface
        peer_file = self._get_peer_file(system)
        peers = self._read_peers(peer_file)

        if any(p.peer_id == peer_id for p in peers):
            return True, f"Peer {peer_id} is enabled (CSV format has no disabled state)"
        else:
            return False, f"Peer {peer_id} not found"

    def disable_peer(self, system: str, peer_id: int) -> Tuple[bool, str]:
        """
        Disable a peer (removes it for CSV format).

        Note: CSV format doesn't support disabled state - to disable, the peer must be removed.

        Args:
            system: System type ('system' or 'public')
            peer_id: Peer ID

        Returns:
            Tuple of (success, message)
        """
        # CSV format doesn't have enabled/disabled state
        # To "disable", we remove it
        return self.remove_peer(system, peer_id)

    def update_peer(
        self,
        system: str,
        peer_id: int,
        password: Optional[str] = None,
        replica: Optional[int] = None,
        peer_name: Optional[str] = None,
        request_key: Optional[int] = None,
        can_inhibit: Optional[int] = None,
        call_priority: Optional[int] = None,
        jitter: Optional[int] = None,
        max_size: Optional[int] = None,
        max_wait: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Update an existing peer.

        Args:
            system: System type ('system' or 'public')
            peer_id: Peer ID to update
            password: Optional new password
            replica: Optional new replica flag
            peer_name: Optional new peer name
            request_key: Optional request_key flag
            can_inhibit: Optional can_inhibit flag
            call_priority: Optional call_priority
            jitter: Optional jitter value
            max_size: Optional max_size value
            max_wait: Optional max_wait value

        Returns:
            Tuple of (success, message)
        """
        try:
            peer_file = self._get_peer_file(system)
            peers = self._read_peers(peer_file)

            # Find and update peer
            found = False
            for peer in peers:
                if peer.peer_id == peer_id:
                    if password is not None:
                        peer.password = password
                    if replica is not None:
                        peer.replica = replica
                    if peer_name is not None:
                        peer.peer_name = peer_name
                    if request_key is not None:
                        peer.request_key = request_key
                    if can_inhibit is not None:
                        peer.can_inhibit = can_inhibit
                    if call_priority is not None:
                        peer.call_priority = call_priority
                    if jitter is not None:
                        peer.jitter = jitter
                    if max_size is not None:
                        peer.max_size = max_size
                    if max_wait is not None:
                        peer.max_wait = max_wait
                    found = True
                    break

            if not found:
                return False, f"Peer {peer_id} not found"

            # Write back
            self._write_peers(peer_file, peers)

            return True, f"Updated peer {peer_id}"

        except Exception as e:
            return False, str(e)

    def edit_peers_interactive(self, system: str) -> Tuple[bool, str]:
        """
        Open peer file in interactive editor (peered or nano/vi).

        Args:
            system: System type ('system' or 'public')

        Returns:
            Tuple of (success, message)
        """
        try:
            peer_file = self._get_peer_file(system)

            # Ensure file exists
            if not peer_file.exists():
                peer_file.parent.mkdir(parents=True, exist_ok=True)
                peer_file.touch()

            # Try peered first (custom DVM peer editor)
            if self.peered_path.exists():
                subprocess.run([str(self.peered_path), "-c", str(peer_file)], check=True)
                return True, f"Peer file edited with {self.peered_path.name}"

            # Fall back to nano or vi
            editors = ["nano", "vi", "vim"]
            for editor in editors:
                try:
                    subprocess.run(["which", editor], capture_output=True, check=True)
                    subprocess.run([editor, str(peer_file)], check=True)
                    return True, f"Peer file edited with {editor}"
                except subprocess.CalledProcessError:
                    continue

            return False, "No suitable editor found (tried: peered, nano, vi, vim)"

        except Exception as e:
            return False, f"Error editing peers: {e}"
