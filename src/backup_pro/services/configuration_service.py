#!/usr/bin/env python3
from __future__ import annotations

import shlex
import shutil
import subprocess
from abc import ABCMeta, abstractmethod

from .dto import TrackedConfigurationDTO
from ..common.singleton import Singleton
from ..common.utils import get_real_gid, get_real_uid
from ..repository import Repository
from ..repository.dao import ConfigurationHandler, ConfigurationStrategy, ScannedConfiguration, TrackedConfiguration

__all__ = [
    "ConfigurationService"
]


class ConfigurationService(metaclass=Singleton):
    def __init__(self):
        self.repository: Repository = Repository()

        self.handlers = (
            GSettingsConfigurationHandler,
        )

    def check(self) -> list[TrackedConfigurationDTO]:
        result = []
        for handler in self.get_handlers():
            result.extend(handler.check())

        return sorted(result, key=lambda c: (c.handler.value, c.key))

    def get_handlers(self, dry_run: bool = False) -> list[BaseConfigurationHandler]:
        return [h(dry_run) for h in self.handlers if h.is_available()]

    def restore(self, dry_run: bool = False) -> None:
        for handler in self.get_handlers(dry_run):
            handler.restore()

    def scan(self) -> None:
        result = []
        for handler in self.get_handlers():
            result.extend(handler.scan())

        self.repository.set_scanned_configurations(result)

    def set(self, conf: TrackedConfiguration) -> None:
        self.repository.set_tracked_configuration(conf)


class BaseConfigurationHandler(metaclass=ABCMeta):
    def __init__(self, handler: ConfigurationHandler, dry_run: bool = False):
        self.dry_run = dry_run
        self.handler = handler
        self.repository = Repository()

    def check(self) -> list[TrackedConfigurationDTO]:
        previous_configurations = self.repository.get_scanned_configurations(handler=self.handler)
        previous_configurations = {conf.key: conf.value for conf in previous_configurations.values()}

        if not previous_configurations:
            return []

        current_configurations = self._get_system_configurations()

        tracked_configurations = self.repository.get_tracked_configurations(handler=self.handler)
        tracked_configurations = {c.key: c for c in tracked_configurations.values()}

        detected_configurations = {}
        for key, current in current_configurations.items():
            detected = TrackedConfigurationDTO(current=current, handler=self.handler, key=key)
            if key in previous_configurations:
                detected.previous = previous_configurations[key]

            if detected.current != detected.previous:
                if key in tracked_configurations:
                    detected.strategy = tracked_configurations[key].strategy
                detected_configurations[key] = detected

        for key, previous in previous_configurations.items():
            if key not in current_configurations:
                detected = TrackedConfigurationDTO(handler=self.handler, key=key, previous=previous)
                if key in tracked_configurations:
                    detected.strategy = tracked_configurations[key].strategy

                detected_configurations[key] = detected

        return [*detected_configurations.values()]

    @abstractmethod
    def _get_system_configurations(self) -> dict[str, str]:
        pass

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        pass

    def restore(self) -> None:
        previous_configurations = self.repository.get_scanned_configurations(handler=self.handler)
        previous_configurations = {c.key: c.value for c in previous_configurations.values()}

        if not previous_configurations:
            return

        current_configurations = self._get_system_configurations()

        tracked_configurations = self.repository.get_tracked_configurations(handler=self.handler)
        tracked_configurations = {c.key: c for c in tracked_configurations.values()}

        for key, previous in previous_configurations.items():
            if key not in tracked_configurations:
                continue

            current = current_configurations.get(key)
            strategy = tracked_configurations[key].strategy

            if strategy == ConfigurationStrategy.Track and current != previous:
                self._restore_configuration(key, previous)

    @abstractmethod
    def _restore_configuration(self, key: str, value: str) -> None:
        pass

    def scan(self) -> list[ScannedConfiguration]:
        configurations = self._get_system_configurations()
        return [ScannedConfiguration(key=key, handler=self.handler, value=value)
                for key, value in configurations.items()]


class GSettingsConfigurationHandler(BaseConfigurationHandler):
    def __init__(self, dry_run: bool = False):
        super().__init__(ConfigurationHandler.GSettings, dry_run)

    def _restore_configuration(self, key: str, value: str) -> None:
        schema, key = key.rsplit(".", 1)
        command = ["gsettings", "set", schema, key, value]
        print(f"# {shlex.join(command)}")
        if not self.dry_run:
            subprocess.run(command, group=get_real_gid(), stdin=subprocess.DEVNULL, user=get_real_uid())

    def _get_system_configurations(self) -> dict[str, str]:
        result = {}
        dump = subprocess.check_output(["gsettings", "list-recursively"], group=get_real_gid(),
                                       stdin=subprocess.DEVNULL, text=True, user=get_real_uid())
        dump = dump.strip().split("\n")
        for line in dump:
            line = line.strip().split(maxsplit=2)
            result[f"{line[0]}.{line[1]}"] = line[2]

        return result

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which("gsettings"))
