#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from argparse import ArgumentParser
from datetime import datetime
from typing import Iterable, Sequence

from .backup_pro import BackupPro
from .common.utils import BackupProException, expand_path, sanitize_path, StrPath
from .constants import DEFAULT_CONF_DIR, DEFAULT_TARGET_DIR
from .repository.dao import *
from .services.dto import *

__all__ = [
    "APP",
    "backup",
    "check",
    "check_configurations",
    "check_packages",
    "diff",
    "main",
    "restore",
    "restore_configurations",
    "restore_files",
    "restore_packages",
    "scan"
]

APP: BackupPro | None = None


def main(args: Sequence[str]) -> int:
    global APP

    args = _parse_args(args)
    APP = None
    try:
        APP = BackupPro(args.conf_dir, args.target_dir)

        if args.command == "backup":
            backup(args.configurations, args.files, args.packages, args.force)
        elif args.command == "check":
            check(args.configurations, args.packages)
        elif args.command == "diff":
            _diff(args)
        elif args.command == "restore":
            restore(args.configurations, args.files, args.packages, args.dry_run, args.interactive)
        elif args.command == "scan":
            _scan(args)
        elif args.command == "settings":
            _change_settings(args)
    except BackupProException as e:
        print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
        return 4
    else:
        return 0
    finally:
        del APP


def _parse_args(args: Sequence[str]) -> argparse.Namespace:
    description = ("A comprehensive backup tool that makes the life easier when backing up/restoring configurations, "
                   "files, packages of the system.")
    epilog = "For more information: https://github.com/simsekhalit/backup-pro"
    backup_strategies = tuple(s.value for s in BackupStrategy.__members__.values())

    main_parser = ArgumentParser("backup-pro", description=description, epilog=epilog)
    main_parser.add_argument("-c", "--conf-dir", default=DEFAULT_CONF_DIR,
                             help="folder that contains the backup-pro configurations. "
                                  "defaults to the current directory",
                             type=expand_path)
    main_parser.add_argument("-t", "--target-dir", default=DEFAULT_TARGET_DIR,
                             help="folder that contains the target backup file. "
                                  "defaults to the current directory",
                             type=expand_path)

    command_parsers = main_parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    backup_parser = command_parsers.add_parser("backup", epilog=epilog, help="backup the system")
    backup_parser.add_argument("-f", "--force", action="store_true",
                               help="overwrite target backup file if it exist. "
                                    "normally, changed files are synchronized (similar to zip -FS parameter)")
    backup_parser.add_argument("-a", "--all", action="store_true",
                               help="backup all. this is the default if none is selected")
    backup_parser.add_argument("--configurations", action="store_true", help="backup configurations")
    backup_parser.add_argument("--files", action="store_true", help="backup files")
    backup_parser.add_argument("--packages", action="store_true", help="backup packages")

    check_parser = command_parsers.add_parser("check", epilog=epilog, help="check configurations and packages")
    check_parser.add_argument("-a", "--all", action="store_true",
                              help="check all. this is the default if none is selected")
    check_parser.add_argument("--configurations", action="store_true", help="check configurations")
    check_parser.add_argument("--packages", action="store_true", help="check packages")

    diff_parser = command_parsers.add_parser("diff", epilog=epilog, help="calculate diff using the previous scans")
    diff_options1 = diff_parser.add_mutually_exclusive_group()
    diff_options1.add_argument("-l", "--list", action="store_true", help="list index snapshots and return")
    diff_options2 = diff_parser.add_mutually_exclusive_group()
    diff_options2.add_argument("-f", "--from-time", help="from which point in time, diff should be "
                                                         "calculated (in seconds). defaults to the second latest "
                                                         "snapshot", type=int)
    diff_options2.add_argument("-t", "--to-time", help="to which point in time, diff should be calculated "
                                                       "(in seconds). defaults to the latest snapshot",
                               type=int)
    diff_parser.add_argument("paths", help="specify paths to calculate diff for. defaults to the root directory",
                             metavar="PATH", nargs="*", type=expand_path)

    restore_parser = command_parsers.add_parser("restore", epilog=epilog,
                                                help="restore the system to the previous backup point")
    restore_parser.add_argument("-i", "--interactive", action="store_true", help="restore in an interactive way")
    restore_parser.add_argument("-n", "--dry-run", action="store_true", help="perform a trial run with no changes made")
    restore_parser.add_argument("-a", "--all", action="store_true",
                                help="restore all. this is the default if none is selected")
    restore_parser.add_argument("--configurations", action="store_true", help="restore configurations")
    restore_parser.add_argument("--files", action="store_true", help="restore files")
    restore_parser.add_argument("--packages", action="store_true", help="restore packages")

    scan_parser = command_parsers.add_parser("scan", epilog=epilog,
                                             help="scan the system to generate filesystem index snapshot that is used "
                                                  "by the diff command")
    scan_options = scan_parser.add_mutually_exclusive_group()
    scan_options.add_argument("-l", "--list", action="store_true", help="list index snapshots and return")
    scan_options.add_argument("--remove", help="remove a snapshot and return", metavar="SNAPSHOT", type=int)
    scan_parser.add_argument("paths", help="specify paths to scan. defaults to the root directory",
                             metavar="PATH", nargs="*", type=sanitize_path)

    settings_parser = command_parsers.add_parser("settings", epilog=epilog, help="change settings of the backup-pro")
    setting_parsers = settings_parser.add_subparsers(dest="setting", metavar="SETTING", required=True)
    setting_parsers.add_parser("restore-conf", epilog=epilog,
                               help="restore backup pro configurations from target backup file")
    add_tracked_path_parser = setting_parsers.add_parser("add-tracked-path", epilog=epilog,
                                                         help="add a path to be tracked for backup")
    add_tracked_path_parser.add_argument("-s", "--strategy", choices=backup_strategies,
                                         default=BackupStrategy.Auto.value,
                                         help=f"strategy for the path. defaults to '{BackupStrategy.Auto.value}'")
    add_tracked_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    remove_tracked_path_parser = setting_parsers.add_parser("remove-tracked-path", epilog=epilog,
                                                            help="remove previously added tracked path")
    remove_tracked_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    add_archive_exclude_path_parser = setting_parsers.add_parser("add-archive-exclude-path", epilog=epilog,
                                                                 help="add a path to be excluded for backup")
    add_archive_exclude_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    remove_archive_exclude_path_parser = setting_parsers.add_parser("remove-archive-exclude-path", epilog=epilog,
                                                                    help="remove previously added archive exclude path")
    remove_archive_exclude_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    add_archive_exclude_pattern_parser = setting_parsers.add_parser("add-archive-exclude-pattern", epilog=epilog,
                                                                    help="add a regex pattern for excluding paths for "
                                                                         "backup")
    add_archive_exclude_pattern_parser.add_argument("pattern", metavar="PATTERN")
    remove_archive_exclude_pattern_parser = setting_parsers.add_parser("remove-archive-exclude-pattern", epilog=epilog,
                                                                       help="remove previously added archive exclude "
                                                                            "pattern")
    remove_archive_exclude_pattern_parser.add_argument("pattern", metavar="PATTERN")
    add_scan_exclude_path_parser = setting_parsers.add_parser("add-scan-exclude-path", epilog=epilog,
                                                              help="add a path to be excluded for scan")
    add_scan_exclude_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    remove_scan_exclude_path_parser = setting_parsers.add_parser("remove-scan-exclude-path", epilog=epilog,
                                                                 help="remove previously added scan exclude path")
    remove_scan_exclude_path_parser.add_argument("path", metavar="PATH", type=sanitize_path)
    add_scan_exclude_pattern_parser = setting_parsers.add_parser("add-scan-exclude-pattern", epilog=epilog,
                                                                 help="add a regex pattern for excluding paths for "
                                                                      "scan")
    add_scan_exclude_pattern_parser.add_argument("pattern", metavar="PATTERN")
    remove_scan_exclude_pattern_parser = setting_parsers.add_parser("remove-scan-exclude-pattern", epilog=epilog,
                                                                    help="remove previously added scan exclude pattern")
    remove_scan_exclude_pattern_parser.add_argument("pattern", metavar="PATTERN")

    args = main_parser.parse_args(args)
    if args.command == "backup" or args.command == "restore":
        if args.all or not (args.configurations or args.files or args.packages):
            args.configurations = True
            args.files = True
            args.packages = True
        del args.all
    elif args.command == "check":
        if args.all or not (args.configurations or args.packages):
            args.configurations = True
            args.packages = True
        del args.all

    return args


def backup(configurations: bool = False, files: bool = False, packages: bool = False, force: bool = False) -> None:
    if packages:
        APP.package_service.scan()
    if configurations:
        APP.configuration_service.scan()
    if files:
        APP.archive_service.backup(force)
    print("Done.")


def check(configurations: bool = False, packages: bool = False) -> None:
    if packages:
        check_packages()
    if configurations:
        check_configurations()
    print("Done.")


def check_packages() -> None:
    packages = [p for p in APP.package_service.check() if not p.ignored]
    _check_packages(packages)


def _check_packages(packages: list[TrackedPackageDTO]) -> None:
    no_change = True
    new_package_exist = any(c for c in packages if c.strategy is None)
    if new_package_exist:
        print(("Choose package strategy:\n"
               "d: mark as dependency\n"
               "i: ignore\n"
               "r: remove\n"
               "t: track\n"
               "S: skip\n"))

    for package in packages:
        key = f"{package.handler.value}/{package.name}"
        if package.strategy == PackageStrategy.Dependency:
            if package.installed:
                no_change = False
                print(f"{key} is manually installed")
        elif package.strategy == PackageStrategy.Remove:
            if package.installed:
                no_change = False
                print(f"{key} is redundant")
        elif package.strategy == PackageStrategy.Track:
            if not package.installed:
                no_change = False
                print(f"{key} is not installed")
        elif package.strategy is None:
            no_change = False
            print(f"{key} is detected")
            strategy = _choose_package_strategy()
            if strategy:
                APP.package_service.set(TrackedPackage(name=package.name, handler=package.handler, strategy=strategy))
            print()

    if no_change:
        print("No package change is detected.")
    else:
        print("Done.")


def _choose_package_strategy() -> PackageStrategy | None:
    strategies = {
        "d": PackageStrategy.Dependency,
        "i": PackageStrategy.Ignore,
        "r": PackageStrategy.Remove,
        "t": PackageStrategy.Track
    }
    choice = _choose(("d", "i", "r", "t", "S"), "s")
    return strategies.get(choice)


def _choose(choices: Iterable[str], default: str) -> str:
    prompt = f"[{'/'.join(choices)}]"
    choices = [c.lower() for c in choices]
    while True:
        choice = input(prompt)
        if not choice:
            return default

        choice = choice.lower()
        if choice in choices:
            return choice


def check_configurations() -> None:
    configurations = APP.configuration_service.check()
    _check_configurations(configurations)


def _check_configurations(configurations: list[TrackedConfigurationDTO]) -> None:
    no_change = True
    new_configuration_exist = any(c for c in configurations if c.strategy is None)
    if new_configuration_exist:
        print(("Choose configuration strategy:\n"
               "i: ignore\n"
               "t: track\n"
               "S: skip\n"))

    for conf in configurations:
        if conf.strategy == ConfigurationStrategy.Track:
            if conf.previous != conf.current:
                no_change = False
                print(f"{conf.handler.value}/{conf.key}\n"
                      f"<{conf.previous}\n"
                      f">{conf.current}\n")
        elif conf.strategy is None:
            no_change = False
            print(f"{conf.handler.value}/{conf.key}\n"
                  f"<{conf.previous}\n"
                  f">{conf.current}")

            strategy = _choose_configuration_strategy()
            if strategy:
                APP.configuration_service.set(TrackedConfiguration(handler=conf.handler, key=conf.key,
                                                                   strategy=strategy))
            print()

    if no_change:
        print("No configuration change is detected.")
    else:
        print("Done.")


def _choose_configuration_strategy() -> ConfigurationStrategy | None:
    strategies = {
        "i": ConfigurationStrategy.Ignore,
        "t": ConfigurationStrategy.Track
    }
    choice = _choose(("i", "t", "S"), "s")
    return strategies.get(choice)


def _diff(args: argparse.Namespace):
    if args.list:
        list_index_snapshots()
    else:
        diff(args.from_time, args.to_time, args.paths)


def diff(from_time: int = None, to_time: int = None, paths: list[StrPath] = None) -> None:
    result = APP.scan_service.diff(from_time, to_time, paths)
    for path in result:
        print(path)


def restore(configurations: bool = False, files: bool = False, packages: bool = False, dry_run: bool = False,
            interactive: bool = False) -> None:
    APP.archive_service.restore_conf(dry_run=dry_run)

    if packages:
        restore_packages(dry_run=dry_run)
    if files:
        restore_files(dry_run=dry_run, interactive=interactive)
    if configurations:
        restore_configurations(dry_run=dry_run)
    print("Done.")


def restore_packages(dry_run: bool = False) -> None:
    packages = [p for p in APP.package_service.check() if not p.ignored]
    check_required = any(p for p in packages if p.strategy is None)
    if check_required:
        _check_packages(packages)

    APP.package_service.restore(dry_run=dry_run)


def restore_files(dry_run: bool = False, interactive: bool = False) -> None:
    APP.archive_service.restore(dry_run, interactive)


def restore_configurations(dry_run: bool = False) -> None:
    configurations = APP.configuration_service.check()
    check_required = any(c for c in configurations if c.strategy is None)
    if check_required:
        _check_configurations(configurations)

    APP.configuration_service.restore(dry_run=dry_run)


def _scan(args: argparse.Namespace) -> None:
    if args.list:
        list_index_snapshots()
    elif args.remove:
        APP.scan_service.remove_index_snapshot(args.remove)
    else:
        scan(args.paths)


def list_index_snapshots() -> None:
    snapshots = APP.scan_service.get_index_snapshot_times()
    if snapshots:
        for snapshot in snapshots:
            formatted = datetime.fromtimestamp(snapshot).isoformat()
            print(f"{snapshot} ({formatted})")
    else:
        print("No snapshots exist yet. Please run the scan command.")


def scan(paths: list[StrPath] = None) -> None:
    APP.scan_service.scan(paths)
    print("Done.")


def _change_settings(args: argparse.Namespace) -> None:
    if args.setting == "restore-conf":
        APP.archive_service.restore_conf(force=True)
    if args.setting == "add-tracked-path":
        APP.archive_service.add_tracked_path(args.path, BackupStrategy(args.strategy))
    elif args.setting == "remove-tracked-path":
        APP.archive_service.remove_tracked_path(args.path)
    elif args.setting == "add-archive-exclude-path":
        APP.archive_service.add_archive_exclude_path(args.path)
    elif args.setting == "remove-archive-exclude-path":
        APP.archive_service.remove_archive_exclude_path(args.path)
    elif args.setting == "add-archive-exclude-pattern":
        APP.archive_service.add_archive_exclude_pattern(args.pattern)
    elif args.setting == "remove-archive-exclude-pattern":
        APP.archive_service.remove_archive_exclude_pattern(args.pattern)
    elif args.setting == "add-scan-exclude-path":
        APP.scan_service.add_scan_exclude_path(args.path)
    elif args.setting == "remove-scan-exclude-path":
        APP.scan_service.remove_scan_exclude_path(args.path)
    elif args.setting == "add-scan-exclude-pattern":
        APP.scan_service.add_scan_exclude_pattern(args.pattern)
    elif args.setting == "remove-scan-exclude-pattern":
        APP.scan_service.remove_scan_exclude_pattern(args.pattern)
