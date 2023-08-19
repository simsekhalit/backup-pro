#!/usr/bin/env python3
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from abc import ABCMeta, abstractmethod

from .dto import TrackedPackageDTO
from ..common.singleton import Singleton
from ..repository import Repository
from ..repository.dao import PackageHandler, PackageStrategy, ScannedPackage, TrackedPackage

__all__ = [
    "PackageService"
]


class PackageService(metaclass=Singleton):
    def __init__(self):
        self.repository = Repository()

        self.handlers = (
            AptPackageHandler,
            FlatpakPackageHandler,
            SnapPackageHandler
        )

    def check(self) -> list[TrackedPackageDTO]:
        result = []
        for handler in self._get_handlers():
            result.extend(handler.check())

        return sorted(result, key=lambda p: (p.handler.value, p.name))

    def _get_handlers(self, dry_run: bool = False) -> list[BasePackageHandler]:
        return [h(dry_run) for h in self.handlers if h.is_available()]

    def restore(self, dry_run: bool = False) -> None:
        for handler in self._get_handlers(dry_run):
            handler.restore()

    def scan(self) -> None:
        result = []
        for handler in self._get_handlers():
            result.extend(handler.scan())

        self.repository.set_scanned_packages(result)

    def set(self, package: TrackedPackage) -> None:
        self.repository.set_tracked_package(package)


class BasePackageHandler(metaclass=ABCMeta):
    def __init__(self, handler: PackageHandler, dry_run: bool = False):
        self.dry_run: bool = dry_run
        self.handler: PackageHandler = handler
        self.repository: Repository = Repository()

    def check(self) -> list[TrackedPackageDTO]:
        current_packages = self._get_installed_packages()

        previous_packages = self.repository.get_scanned_packages(handler=self.handler)
        previous_packages = [pkg.name for pkg in previous_packages.values()]

        tracked_packages = self.repository.get_tracked_packages(handler=self.handler)
        tracked_packages = {pkg.name: pkg for pkg in tracked_packages.values()}

        detected_packages = {}
        for name in current_packages:
            detected = TrackedPackageDTO(handler=self.handler, installed=True, name=name)
            if name in tracked_packages:
                package = tracked_packages[name]
                detected.ignored = self._is_ignored(package)
                detected.strategy = package.strategy

            detected_packages[name] = detected

        for name in previous_packages:
            if name not in detected_packages:
                detected = TrackedPackageDTO(handler=self.handler, name=name)
                if name in tracked_packages:
                    package = tracked_packages[name]
                    detected.ignored = self._is_ignored(package)
                    detected.strategy = package.strategy

                detected_packages[name] = detected

        return [*detected_packages.values()]

    def restore(self) -> None:
        packages_to_install = []
        packages_to_make_dependency = []
        packages_to_remove = []

        installed_packages = self._get_installed_packages()
        tracked_packages = self.repository.get_tracked_packages(self.handler)
        tracked_packages = (p for p in tracked_packages.values() if not self._is_ignored(p))
        for package in tracked_packages:
            if package.strategy == PackageStrategy.Dependency and package.name in installed_packages:
                packages_to_make_dependency.append(package)
            elif package.strategy == PackageStrategy.Remove and package.name in installed_packages:
                packages_to_remove.append(package)
            elif package.strategy == PackageStrategy.Track and package.name not in installed_packages:
                packages_to_install.append(package)

        if packages_to_make_dependency:
            commands = self._get_make_dependency_commands(packages_to_make_dependency)
            for command in commands:
                self._run_command(command)

        if packages_to_remove:
            commands = self._get_remove_commands(packages_to_remove)
            for command in commands:
                self._run_command(command)

        if packages_to_install:
            commands = self._get_install_commands(packages_to_install)
            for command in commands:
                self._run_command(command)

    def _run_command(self, command: list[str]) -> None:
        print(f"# {shlex.join(command)}")
        if not self.dry_run:
            if self._is_interactive():
                subprocess.run(command, stderr=subprocess.STDOUT)
            else:
                subprocess.run(command, env={"DEBIAN_FRONTEND": "noninteractive"}, stdin=subprocess.DEVNULL,
                               stderr=subprocess.STDOUT)

    @abstractmethod
    def _get_installed_packages(self) -> set[str]:
        pass

    @abstractmethod
    def _get_remove_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        pass

    @abstractmethod
    def _get_install_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        pass

    @abstractmethod
    def _get_make_dependency_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        pass

    def scan(self) -> list[ScannedPackage]:
        packages = self._get_installed_packages()
        return [ScannedPackage(name=p, handler=self.handler) for p in packages]

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        pass

    @abstractmethod
    def _is_ignored(self, package: TrackedPackage) -> bool:
        pass

    @staticmethod
    def _is_interactive() -> bool:
        return sys.stdout.isatty()


class AptPackageHandler(BasePackageHandler):
    def __init__(self, dry_run: bool = False):
        super().__init__(PackageHandler.Apt, dry_run)

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which("apt"))

    def _is_ignored(self, package: TrackedPackage) -> bool:
        return package.strategy == PackageStrategy.Ignore

    def _get_install_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        if self._is_interactive():
            return [["apt", "install", *(p.name for p in packages)]]
        else:
            return [["apt", "install", "-y", *(p.name for p in packages)]]

    def _get_installed_packages(self) -> set[str]:
        output = subprocess.check_output(["apt-mark", "showmanual"], stdin=subprocess.DEVNULL, text=True)
        output = output.strip().split("\n")
        return {*(p.strip() for p in output)}

    def _get_make_dependency_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        return [["apt-mark", "auto", *(p.name for p in packages)]]

    def _get_remove_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        if self._is_interactive():
            return [["apt", "purge", *(p.name for p in packages)]]
        else:
            return [["apt", "purge", "-y", *(p.name for p in packages)]]


class FlatpakPackageHandler(BasePackageHandler):
    def __init__(self, dry_run: bool = False):
        super().__init__(PackageHandler.Flatpak, dry_run)

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which("flatpak"))

    def _is_ignored(self, package: TrackedPackage) -> bool:
        return package.strategy in (PackageStrategy.Dependency, PackageStrategy.Ignore)

    def _get_install_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        if self._is_interactive():
            return [["flatpak", "install", *(p.name for p in packages)]]
        else:
            return [["flatpak", "install", "-y", "--noninteractive", *(p.name for p in packages)]]

    def _get_installed_packages(self) -> set[str]:
        output = subprocess.check_output(["flatpak", "list", "--app", "--columns", "application"],
                                         stdin=subprocess.DEVNULL, text=True)
        packages = output.strip().split("\n")[1:]
        return {p.strip() for p in packages}

    def _get_make_dependency_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        return []

    def _get_remove_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        if self._is_interactive():
            return [["flatpak", "uninstall", "--delete-data", *(p.name for p in packages)]]
        else:
            return [["flatpak", "uninstall", "-y", "--delete-data", "--noninteractive", *(p.name for p in packages)]]


class SnapPackageHandler(BasePackageHandler):
    def __init__(self, dry_run: bool = False):
        super().__init__(PackageHandler.Snap, dry_run)

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which("snap"))

    def _is_ignored(self, package: TrackedPackage) -> bool:
        return package.strategy in (PackageStrategy.Dependency, PackageStrategy.Ignore)

    def _get_install_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        return [["snap", "install", "--classic", p.name] for p in packages]

    def _get_installed_packages(self) -> set[str]:
        output = subprocess.check_output(["snap", "list"], stdin=subprocess.DEVNULL, text=True)
        output = output.strip().split("\n")[1:]
        packages = {p.strip().split(maxsplit=1)[0].strip() for p in output}
        return packages

    def _get_make_dependency_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        return []

    def _get_remove_commands(self, packages: list[TrackedPackage]) -> list[list[str]]:
        return [["snap", "remove", "--purge", p.name] for p in packages]
