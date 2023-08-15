#!/usr/bin/env python3
from __future__ import annotations

from enum import Enum

from attrs import define

from ..common.entity import BaseEntity
from ..repository.dao import ConfigurationHandler, ConfigurationStrategy, PackageHandler, PackageStrategy

__all__ = [
    "BackupStatus",
    "TrackedConfigurationDTO",
    "TrackedPackageDTO"
]


class BackupStatus(Enum):
    Different = "different"
    Missing = "missing"
    Redundant = "redundant"
    Synced = "synced"


@define
class TrackedConfigurationDTO(BaseEntity):
    handler: ConfigurationHandler
    key: str
    current: str | None = None
    previous: str | None = None
    strategy: ConfigurationStrategy | None = None


@define
class TrackedPackageDTO(BaseEntity):
    handler: PackageHandler
    name: str
    ignored: bool = False
    installed: bool = False
    strategy: PackageStrategy | None = None
