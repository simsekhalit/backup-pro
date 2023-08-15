#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

import attrs
from attrs import define, field
from cattrs.preconf.json import JsonConverter

from .dao import *
from ..common.entity import json_converter
from ..common.singleton import Singleton
from ..common.utils import AnyPath, expand_path, json_dump, json_load, mkdir
from ..constants import *

__all__ = [
    "Repository"
]


class Repository(metaclass=Singleton):
    def __init__(self):
        self.archive_exclude_paths: set[Path] = set()
        self.archive_exclude_patterns: set[str] = set()
        self.archive_metadata: dict[Path, ArchiveMetadata] = {}
        self.conf_dir: Path = Path(DEFAULT_CONF_DIR, CONF_HOLDER)
        self.converter: JsonConverter = json_converter
        self.scan_exclude_paths: set[Path] = set()
        self.scan_exclude_patterns: set[str] = set()
        self.scanned_configurations: dict[str, ScannedConfiguration] = {}
        self.scanned_packages: dict[str, ScannedPackage] = {}
        self.settings: dict[str, str] = {}
        self.target_dir: Path = Path(DEFAULT_TARGET_DIR)
        self.tracked_configurations: dict[str, TrackedConfiguration] = {}
        self.tracked_packages: dict[str, TrackedPackage] = {}
        self.tracked_paths: dict[Path, TrackedPath] = {}

    def load(self, conf: dict = None, state: dict = None) -> None:
        self._load_conf(conf)
        self._load_state(state)

    def _load_conf(self, conf: dict = None) -> None:
        if conf is None:
            try:
                conf = json_load(self.get_conf_path())
            except FileNotFoundError:
                return

        conf = self.converter.structure(conf, Config)
        for key in attrs.fields_dict(Config):
            setattr(self, key, getattr(conf, key))

    def _load_state(self, state: dict = None) -> None:
        if state is None:
            try:
                state = json_load(self.get_state_path())
            except FileNotFoundError:
                return

        state = self.converter.structure(state, State)
        for key in attrs.fields_dict(State):
            setattr(self, key, getattr(state, key))

    def save(self) -> None:
        self._save_conf()
        self._save_state()

    def _save_conf(self) -> None:
        mkdir(self.get_conf_dir())
        conf = Config(**{k: getattr(self, k) for k in attrs.fields_dict(Config)})
        conf = self.converter.unstructure(conf)
        json_dump(conf, self.get_conf_path(), pretty=True)

    def _save_state(self) -> None:
        mkdir(self.get_conf_dir())
        state = State(**{k: getattr(self, k) for k in attrs.fields_dict(State)})
        state = self.converter.unstructure(state)
        json_dump(state, self.get_state_path(), pretty=True)

    def get_archive_exclude_paths(self) -> set[Path]:
        return self.archive_exclude_paths.copy()

    def remove_archive_exclude_path(self, path: Path) -> None:
        self.archive_exclude_paths.discard(path)
        self._save_conf()

    def set_archive_exclude_path(self, path: Path) -> None:
        self.archive_exclude_paths.add(path)
        self._save_conf()

    def get_archive_exclude_patterns(self) -> set[str]:
        return self.archive_exclude_patterns.copy()

    def remove_archive_exclude_pattern(self, pattern: str) -> None:
        self.archive_exclude_patterns.discard(pattern)
        self._save_conf()

    def set_archive_exclude_pattern(self, pattern: str) -> None:
        self.archive_exclude_patterns.add(pattern)
        self._save_conf()

    def get_archive_metadata(self) -> dict[Path, ArchiveMetadata]:
        return {k: v.copy() for k, v in self.archive_metadata.items()}

    def set_archive_metadata(self, metadata: dict[Path, ArchiveMetadata]) -> None:
        self.archive_metadata = {k: v.copy() for k, v in metadata.items()}
        self._save_state()

    def get_conf_dir(self) -> Path:
        return self.conf_dir

    def set_conf_dir(self, conf_dir: AnyPath) -> None:
        self.conf_dir = expand_path(Path(conf_dir, CONF_HOLDER))

    def get_conf_path(self) -> Path:
        return Path(self.conf_dir, CONF_FILE)

    def get_index_snapshot(self, snapshot_time: int) -> IndexSnapshot | None:
        key = Path(self._get_index_snapshots_path(), f"{snapshot_time}.json")
        try:
            return self.converter.structure(json_load(key), IndexSnapshot)
        except FileNotFoundError:
            return

    def _get_index_snapshots_path(self) -> Path:
        return Path(self.get_conf_dir(), INDEX_SNAPSHOTS_DIR)

    def remove_index_snapshot(self, snapshot_time: int) -> None:
        key = Path(self._get_index_snapshots_path(), f"{snapshot_time}.json")
        try:
            os.remove(key)
        except FileNotFoundError:
            pass

    def set_index_snapshot(self, snapshot: IndexSnapshot) -> None:
        mkdir(self._get_index_snapshots_path())
        key = Path(self._get_index_snapshots_path(), f"{snapshot.time}.json")
        json_dump(self.converter.unstructure(snapshot), key, pretty=False)

    def get_index_snapshot_times(self) -> list[int]:
        try:
            return sorted(int(p.name.removesuffix(".json")) for p in self._get_index_snapshots_path().iterdir())
        except FileNotFoundError:
            return []

    def get_scan_exclude_paths(self) -> set[Path]:
        return self.scan_exclude_paths.copy()

    def remove_scan_exclude_path(self, path: Path) -> None:
        self.scan_exclude_paths.discard(path)
        self._save_conf()

    def set_scan_exclude_path(self, path: Path) -> None:
        self.scan_exclude_paths.add(path)
        self._save_conf()

    def get_scan_exclude_patterns(self) -> set[str]:
        return self.scan_exclude_patterns.copy()

    def remove_scan_exclude_pattern(self, pattern: str) -> None:
        self.scan_exclude_patterns.discard(pattern)
        self._save_conf()

    def set_scan_exclude_pattern(self, pattern: str) -> None:
        self.scan_exclude_patterns.add(pattern)
        self._save_conf()

    def get_scanned_configurations(self, handler: ConfigurationHandler = None) -> dict[str, ScannedConfiguration]:
        if handler is None:
            return {k: v.copy() for k, v in self.scanned_configurations.items()}
        else:
            return {k: v.copy() for k, v in self.scanned_configurations.items() if v.handler == handler}

    def set_scanned_configurations(self, configurations: list[ScannedConfiguration]) -> None:
        self.scanned_configurations = {f"{c.handler}/{c.key}": c.copy() for c in configurations}
        self._save_state()

    def get_scanned_packages(self, handler: PackageHandler = None) -> dict[str, ScannedPackage]:
        if handler is None:
            return {k: v.copy() for k, v in self.scanned_packages.items()}
        else:
            return {k: v.copy() for k, v in self.scanned_packages.items() if v.handler == handler}

    def set_scanned_packages(self, packages: list[ScannedPackage]) -> None:
        self.scanned_packages = {f"{p.handler}/{p.name}": p.copy() for p in packages}
        self._save_state()

    def get_settings(self) -> dict[str, str]:
        return self.settings.copy()

    def set_settings(self, key: str, value: str) -> None:
        self.settings[key] = value
        self._save_conf()

    def get_state_path(self) -> Path:
        return Path(self.get_conf_dir(), STATE_FILE)

    def get_target_path(self) -> Path:
        return Path(self.target_dir, TARGET_FILE)

    def set_target_dir(self, target_dir: AnyPath) -> None:
        self.target_dir = expand_path(target_dir)

    def get_tracked_configurations(self, handler: ConfigurationHandler = None) -> dict[str, TrackedConfiguration]:
        if handler is None:
            return {k: v.copy() for k, v in self.tracked_configurations.items()}
        else:
            return {k: v.copy() for k, v in self.tracked_configurations.items() if v.handler == handler}

    def set_tracked_configuration(self, configuration: TrackedConfiguration) -> None:
        self.tracked_configurations[f"{configuration.handler.value}/{configuration.key}"] = configuration.copy()
        self._save_conf()

    def get_tracked_packages(self, handler: PackageHandler = None) -> dict[str, TrackedPackage]:
        if handler is None:
            return {k: v.copy() for k, v in self.tracked_packages.items()}
        else:
            return {k: v.copy() for k, v in self.tracked_packages.items() if v.handler == handler}

    def set_tracked_package(self, package: TrackedPackage) -> None:
        self.tracked_packages[f"{package.handler.value}/{package.name}"] = package.copy()
        self._save_conf()

    def get_tracked_paths(self) -> dict[Path, TrackedPath]:
        return {k: v.copy() for k, v in self.tracked_paths.items()}

    def remove_tracked_path(self, path: Path) -> None:
        try:
            del self.tracked_paths[path]
        except KeyError:
            pass
        else:
            self._save_conf()

    def set_tracked_path(self, tracked_path: TrackedPath) -> None:
        self.tracked_paths[tracked_path.path] = tracked_path.copy()
        self._save_conf()


@define
class Config:
    archive_exclude_paths: set[Path] = field(factory=set)
    archive_exclude_patterns: set[str] = field(factory=set)
    scan_exclude_paths: set[Path] = field(factory=set)
    scan_exclude_patterns: set[str] = field(factory=set)
    settings: dict[str, str] = field(factory=dict)
    tracked_configurations: dict[str, TrackedConfiguration] = field(factory=dict)
    tracked_packages: dict[str, TrackedPackage] = field(factory=dict)
    tracked_paths: dict[str, TrackedPath] = field(factory=dict)


@define
class State:
    archive_metadata: dict[Path, ArchiveMetadata] = field(factory=dict)
    scanned_configurations: dict[str, ScannedConfiguration] = field(factory=dict)
    scanned_packages: dict[str, ScannedPackage] = field(factory=dict)
