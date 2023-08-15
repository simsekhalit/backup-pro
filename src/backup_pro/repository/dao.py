#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
from enum import Enum
from functools import singledispatchmethod
from pathlib import Path

from attrs import define

from ..common.entity import BaseEntity

__all__ = [
    "ArchiveMetadata",
    "BackupStrategy",
    "ConfigurationHandler",
    "ConfigurationStrategy",
    "IndexMetadata",
    "IndexSnapshot",
    "PackageHandler",
    "ScannedConfiguration",
    "ScannedPackage",
    "TrackedConfiguration",
    "TrackedPackage",
    "TrackedPath",
    "PackageStrategy"
]


class BackupStrategy(Enum):
    Auto = "auto"
    BackupOnly = "backup-only"
    Manual = "manual"


class ConfigurationHandler(Enum):
    GSettings = "gsettings"


class ConfigurationStrategy(Enum):
    Ignore = "ignore"
    Track = "track"


class PackageHandler(Enum):
    Apt = "apt"
    Flatpak = "flatpak"
    Snap = "snap"


class PackageStrategy(Enum):
    Dependency = "dependency"
    Ignore = "ignore"
    Remove = "remove"
    Track = "track"


@define(eq=False)
class ArchiveMetadata(BaseEntity):
    path: str
    group: str | None = None
    mode: int | None = None
    mtime_ns: int | None = None
    size: int | None = None
    user: str | None = None

    def __eq__(self, other: ArchiveMetadata):
        return self.group == other.group \
            and self.mode == other.mode \
            and self.mtime_ns // 10 ** 9 == other.mtime_ns // 10 ** 9 \
            and self.path == other.path \
            and self.size == other.size \
            and self.user == other.user

    @singledispatchmethod
    def is_data_different(self, other: ArchiveMetadata) -> bool:
        return stat.S_IFMT(self.mode) != stat.S_IFMT(other.mode) \
            or self.mtime_ns // 10 ** 9 != other.mtime_ns // 10 ** 9 \
            or self.size != other.size

    @is_data_different.register
    def _(self, stat_result: os.stat_result) -> bool:
        return stat.S_IFMT(self.mode) != stat.S_IFMT(stat_result.st_mode) \
            or self.mtime_ns // 10 ** 9 != stat_result.st_mtime_ns // 10 ** 9 \
            or self.size != stat_result.st_size


@define
class IndexMetadata(BaseEntity):
    mtime: int
    size: int


@define
class IndexSnapshot(BaseEntity):
    time: int
    paths: tuple[Path, ...]
    metadata: dict[Path, IndexMetadata]


@define
class ScannedConfiguration(BaseEntity):
    handler: ConfigurationHandler
    key: str
    value: str


@define
class ScannedPackage(BaseEntity):
    name: str
    handler: PackageHandler


@define
class TrackedConfiguration(BaseEntity):
    handler: ConfigurationHandler
    key: str
    strategy: ConfigurationStrategy


@define
class TrackedPackage(BaseEntity):
    name: str
    handler: PackageHandler
    strategy: PackageStrategy


@define
class TrackedPath(BaseEntity):
    path: Path
    strategy: BackupStrategy
