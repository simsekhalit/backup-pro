#!/usr/bin/env python3
from __future__ import annotations

from .repository import Repository
from .services import ArchiveService, ConfigurationService, PackageService, ScanService

__all__ = [
    "BackupPro"
]


class BackupPro:
    def __init__(self, conf_dir: str, target_dir: str):
        self.repository: Repository = Repository()
        self.repository.set_conf_dir(conf_dir)
        self.repository.set_target_dir(target_dir)
        self.repository.load()

        self.archive_service: ArchiveService = ArchiveService()
        self.configuration_service: ConfigurationService = ConfigurationService()
        self.package_service: PackageService = PackageService()
        self.scan_service: ScanService = ScanService()
