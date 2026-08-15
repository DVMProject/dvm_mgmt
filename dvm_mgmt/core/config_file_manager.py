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
"""Safe management of explicitly configured YAML files."""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import yaml

from dvm_mgmt.core.config import ConsoleConfig, EditableConfigFile


class ConfigFileManager:
    """Read, validate, save, and restore allowlisted YAML configuration files."""

    def __init__(self, config: ConsoleConfig):
        self.config = config

    def resolve(self, file_id: str) -> EditableConfigFile:
        for item in self.config.editable_config_files:
            if item.id == str(file_id):
                return item
        raise KeyError("Configuration file is not allowlisted")

    def read(self, file_id: str) -> Tuple[EditableConfigFile, str]:
        item = self.resolve(file_id)
        if not item.path.is_file():
            raise FileNotFoundError(str(item.path))
        if item.path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Configuration file exceeds the 2 MiB editor limit")
        return item, item.path.read_text(encoding="utf-8")

    @staticmethod
    def validate(content: str) -> None:
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            problem = getattr(exc, "problem", None) or str(exc)
            raise ValueError(f"Invalid YAML{location}: {problem}") from exc

    @staticmethod
    def _backup(path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        backup = path.with_name(f"{path.name}.backup.{stamp}")
        shutil.copy2(path, backup)
        os.utime(backup, None)
        return backup

    def save(self, file_id: str, content: str) -> Path:
        item = self.resolve(file_id)
        path = item.path
        if not path.is_file():
            raise FileNotFoundError(str(path))
        if len(content.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Configuration file exceeds the 2 MiB editor limit")
        self.validate(content)
        backup = self._backup(path)
        mode = path.stat().st_mode & 0o7777
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(mode)
            os.replace(str(temporary), str(path))
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return backup

    def backups(self, file_id: str) -> List[Path]:
        item = self.resolve(file_id)
        prefix = f"{item.path.name}.backup."
        return sorted(
            (path for path in item.path.parent.iterdir() if path.is_file() and path.name.startswith(prefix)),
            reverse=True,
        )

    def restore(self, file_id: str, backup_name: str) -> Path:
        item = self.resolve(file_id)
        matches = {path.name: path for path in self.backups(file_id)}
        source = matches.get(Path(backup_name).name)
        if source is None or Path(backup_name).name != backup_name:
            raise KeyError("Backup is not available for this configuration file")
        content = source.read_text(encoding="utf-8")
        return self.save(file_id, content)

    def delete_backup(self, file_id: str, backup_name: str) -> Path:
        """Delete one revision belonging to the selected allowlisted file."""
        normalized_name = Path(backup_name).name
        if normalized_name != backup_name:
            raise KeyError("Backup is not available for this configuration file")

        matches = {path.name: path for path in self.backups(file_id)}
        backup = matches.get(normalized_name)
        if backup is None:
            raise KeyError("Backup is not available for this configuration file")

        backup.unlink()
        return backup
