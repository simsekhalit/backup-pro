#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import stat
import sys
import time
from pathlib import Path
from re import Pattern
from typing import Iterable

from ..common.singleton import Singleton
from ..common.utils import BackupProException, expand_path, sanitize_path, stat_path, StrPath
from ..repository import Repository
from ..repository.dao import IndexMetadata, IndexSnapshot

__all__ = [
    "ScanService"
]


class ScanService(metaclass=Singleton):
    def __init__(self):
        self.repository: Repository = Repository()

    @staticmethod
    def diff(from_time: int = None, to_time: int = None, paths: list[StrPath] = None) -> list[Path]:
        paths = [] if paths is None else [sanitize_path(p) for p in paths]
        return ScanHandler().diff(from_time, to_time, paths)

    def get_index_snapshot_times(self) -> list[int]:
        return self.repository.get_index_snapshot_times()

    def remove_index_snapshot(self, snapshot_time: int) -> None:
        self.repository.remove_index_snapshot(snapshot_time)

    @staticmethod
    def scan(paths: list[StrPath] = None) -> None:
        paths = [] if paths is None else [sanitize_path(p) for p in paths]
        ScanHandler().scan(paths)

    def add_scan_exclude_path(self, path: StrPath) -> None:
        self.repository.set_scan_exclude_path(sanitize_path(path))

    def remove_scan_exclude_path(self, path: StrPath) -> None:
        self.repository.remove_scan_exclude_path(sanitize_path(path))

    def add_scan_exclude_pattern(self, pattern: str) -> None:
        self.repository.set_scan_exclude_pattern(pattern)

    def remove_scan_exclude_pattern(self, pattern: str) -> None:
        self.repository.remove_scan_exclude_pattern(pattern)


class ScanHandler:
    def __init__(self):
        self.repository: Repository = Repository()

        self.metadata: dict[Path, IndexMetadata] = {}
        self.scan_exclude_paths: set[Path] = {expand_path(p) for p in self.repository.get_scan_exclude_paths()}
        self.scan_exclude_patterns: list[Pattern[str]] = [re.compile(p)
                                                          for p in self.repository.get_scan_exclude_patterns()]

    def diff(self, from_time: int = None, to_time: int = None, paths: list[Path] = None) -> list[Path]:
        from_snapshot, to_snapshot = self._get_snapshots(from_time, to_time)
        paths = self._calculate_selected_paths(from_snapshot.paths, to_snapshot.paths, paths)
        result = self._calculate_diff(from_snapshot, to_snapshot, paths)
        return sorted(result)

    def _get_snapshots(self, from_time: int = None, to_time: int = None) -> tuple[IndexSnapshot, IndexSnapshot]:
        snapshot_times = self.repository.get_index_snapshot_times()
        if not snapshot_times:
            raise BackupProException("Scan must be called prior to calculating diff.")

        if to_time is not None:
            to_snapshot = self.repository.get_index_snapshot(to_time)
        else:
            to_snapshot = self.repository.get_index_snapshot(snapshot_times[-1])

        if to_snapshot is None:
            raise BackupProException(f"There is no index with given time: {to_time}")

        if from_time is not None:
            from_snapshot = self.repository.get_index_snapshot(from_time)
        elif len(snapshot_times) < 2:
            raise BackupProException("At least two scan snapshots are required to calculate diff when from_time "
                                     "is not given.")
        else:
            from_snapshot = self.repository.get_index_snapshot(snapshot_times[-2])

        if from_snapshot is None:
            from_snapshot = IndexSnapshot(from_time, (Path(Path.cwd().anchor),), {})

        return from_snapshot, to_snapshot

    def _calculate_selected_paths(self, from_paths: Iterable[Path], to_paths: Iterable[Path],
                                  selected_paths: Iterable[Path]) -> list[Path]:
        from_paths = (expand_path(p) for p in from_paths)
        to_paths = (expand_path(p) for p in to_paths)

        result = self._calculate_common_paths(from_paths, to_paths)

        if selected_paths:
            selected_paths = (expand_path(p) for p in selected_paths)
            result = self._calculate_common_paths(result, selected_paths)

        return sorted(result)

    @staticmethod
    def _calculate_common_paths(paths1: Iterable[Path], paths2: Iterable[Path]) -> set[Path]:
        result = set()
        for path1 in paths1:
            for path2 in paths2:
                if path1.is_relative_to(path2):
                    result.add(path1)
                elif path2.is_relative_to(path1):
                    result.add(path2)

        return result

    def _calculate_diff(self, from_snapshot: IndexSnapshot, to_snapshot: IndexSnapshot,
                        selected_paths: list[Path]) -> set[Path]:
        from_time = from_snapshot.time
        from_snapshot = {expand_path(k): v for k, v in from_snapshot.metadata.items()}
        to_snapshot = {expand_path(k): v for k, v in to_snapshot.metadata.items()}
        result = set()
        for path, to_metadata in to_snapshot.items():
            if not self._is_path_selected(selected_paths, path):
                continue

            from_metadata = from_snapshot.get(path)
            if (from_metadata is not None and from_metadata != to_metadata) or to_metadata.mtime > from_time:
                result.add(path)

        for path, from_metadata in from_snapshot.items():
            if path not in to_snapshot and self._is_path_selected(selected_paths, path):
                result.add(path)

        return result

    @staticmethod
    def _is_path_selected(paths: list[Path], arg: Path) -> bool:
        return any(p for p in paths if arg.is_relative_to(p))

    def scan(self, paths: list[Path] = None) -> None:
        if paths:
            paths = sorted(paths)
        else:
            paths = (Path(Path.cwd().anchor),)

        for path in paths:
            self._scan_path(path)

        self.repository.set_index_snapshot(IndexSnapshot(int(time.time()), tuple(paths), self.metadata))

    def _scan_path(self, path: Path) -> None:
        if path in self.metadata:
            return

        system_path = expand_path(path)
        if self._is_excluded_path(system_path):
            return

        try:
            stat_result = stat_path(system_path)
        except OSError as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
            return

        if stat_result is None:
            return

        if stat.S_ISDIR(stat_result.st_mode):
            self.metadata[path] = self._generate_index_metadata(stat_result)
            self._scan_dir(path, system_path)
        elif stat.S_ISREG(stat_result.st_mode) or stat.S_ISLNK(stat_result.st_mode):
            self.metadata[path] = self._generate_index_metadata(stat_result)

    def _is_excluded_path(self, path: Path) -> bool:
        if path in self.scan_exclude_paths:
            return True

        for pattern in self.scan_exclude_patterns:
            if pattern.search(os.fspath(path)):
                return True

        return False

    @staticmethod
    def _generate_index_metadata(stat_result: os.stat_result) -> IndexMetadata:
        return IndexMetadata(
            mtime=int(stat_result.st_mtime),
            size=stat_result.st_size
        )

    def _scan_dir(self, path: Path, system_path: Path) -> None:
        try:
            children = sorted(c.name for c in system_path.iterdir())
        except OSError as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
            return

        for child in children:
            self._scan_path(path / child)
