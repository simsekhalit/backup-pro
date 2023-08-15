#!/usr/bin/env python3
from __future__ import annotations

import grp
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from abc import ABCMeta
from datetime import datetime
from pathlib import Path, PurePosixPath
from re import Pattern

from attrs import define, evolve, field

from ..common.singleton import Singleton
from ..common.utils import BackupProException, chstat, expand_path, get_real_gid, get_real_uid, json_loads, \
    mkdir, remove, sanitize_path, stat_path, strip_anchor, StrPath
from ..constants import *
from ..repository import Repository
from ..repository.dao import ArchiveMetadata, BackupStrategy, TrackedPath

__all__ = [
    "ArchiveService"
]


class ArchiveService(metaclass=Singleton):
    def __init__(self):
        self.repository: Repository = Repository()

    def add_archive_exclude_path(self, path: StrPath) -> None:
        self.repository.set_archive_exclude_path(sanitize_path(path))

    def remove_archive_exclude_path(self, path: StrPath) -> None:
        self.repository.remove_archive_exclude_path(sanitize_path(path))

    def add_archive_exclude_pattern(self, pattern: str) -> None:
        self.repository.set_archive_exclude_pattern(pattern)

    def remove_archive_exclude_pattern(self, pattern: str) -> None:
        self.repository.remove_archive_exclude_pattern(pattern)

    @staticmethod
    def backup(force: bool = False) -> None:
        BackupHandler(force).backup()

    @staticmethod
    def restore(dry_run: bool = False, interactive: bool = False) -> None:
        with RestoreHandler(dry_run, interactive) as h:
            h.restore()

    @staticmethod
    def restore_conf(dry_run: bool = False, force: bool = False) -> None:
        with RestoreHandler(dry_run) as h:
            h.restore_conf(force)

    def add_tracked_path(self, path: StrPath, strategy: BackupStrategy) -> None:
        self.repository.set_tracked_path(TrackedPath(sanitize_path(path), strategy))

    def remove_tracked_path(self, path: StrPath) -> None:
        self.repository.remove_tracked_path(sanitize_path(path))


class BaseArchiveHandler(metaclass=ABCMeta):
    ARCHIVE_PWD = "backup-pro"
    ARCHIVE_PWDB = b"backup-pro"

    def __init__(self):
        self.archive_exclude_paths: set[Path] = set()
        self.archive_exclude_patterns: list[Pattern[str]] = []
        self.system_groups: dict[int | str | None, int | str | None] = {}
        self.system_users: dict[int | str | None, int | str | None] = {}

    @staticmethod
    def _generate_archive_path(path: Path, st_mode: int) -> str:
        path = strip_anchor(path)
        if stat.S_ISDIR(st_mode):
            return path.as_posix() + "/"
        else:
            return path.as_posix()

    def _is_path_excluded(self, path: Path) -> bool:
        if path in self.archive_exclude_paths:
            return True

        for pattern in self.archive_exclude_patterns:
            if pattern.search(os.fspath(path)) is not None:
                return True

        return False

    def _resolve_system_user(self, user: int | str | None) -> int | str | None:
        if user in self.system_users:
            return self.system_users[user]

        if user is None:
            result = get_real_uid()
        elif user == get_real_uid():
            result = None
        elif isinstance(user, int):
            try:
                result = pwd.getpwuid(user).pw_name
            except (AttributeError, KeyError, ValueError):
                result = None
        else:
            try:
                result = pwd.getpwnam(user).pw_uid
            except (AttributeError, KeyError, ValueError):
                result = get_real_uid()

        self.system_users[user] = result
        return result

    def _resolve_system_group(self, group: int | str | None) -> int | str | None:
        if group in self.system_groups:
            return self.system_groups[group]

        if group is None:
            result = get_real_gid()
        elif group == get_real_gid():
            result = None
        elif isinstance(group, int):
            try:
                result = grp.getgrgid(group).gr_name
            except (AttributeError, KeyError, ValueError):
                result = None
        else:
            try:
                result = grp.getgrnam(group).gr_gid
            except (AttributeError, KeyError, ValueError):
                result = get_real_gid()

        self.system_groups[group] = result
        return result

    @staticmethod
    def _is_supported_type(stat_result: os.stat_result) -> bool:
        return stat.S_ISDIR(stat_result.st_mode) or stat.S_ISLNK(stat_result.st_mode) \
            or stat.S_ISREG(stat_result.st_mode)


class BackupHandler(BaseArchiveHandler):
    def __init__(self, force: bool = False):
        super().__init__()
        self.force: bool = force
        self.repository: Repository = Repository()

        self.conf_dir: Path = self.repository.get_conf_dir()
        self.target_path: Path = self.repository.get_target_path()

        self.archive_exclude_paths: set[Path] = {expand_path(p) for p in self.repository.get_archive_exclude_paths()}
        self.archive_exclude_paths.add(self.conf_dir)
        self.archive_exclude_paths.add(self.target_path)
        self.archive_exclude_patterns: list[Pattern[str]] = [re.compile(p)
                                                             for p in self.repository.get_archive_exclude_patterns()]

        self.archive_metadata: dict[Path, ArchiveMetadata | None] = {}
        self.stat_cache: dict[Path, os.stat_result] = {}
        self.result: set[Path] = set()
        self.scan_cache: set[Path] = set()
        tracked_paths = (BackupPath(tp.path) for tp in self.repository.get_tracked_paths().values())
        self.tracked_paths: dict[Path, BackupPath] = {tp.system_path: tp for tp in tracked_paths}

    def backup(self) -> None:
        for path in self.tracked_paths.values():
            self._scan_path(evolve(path))

        self.archive_metadata = {k: v for k, v in self.archive_metadata.items() if v is not None}

        if self.force or self._is_archive_changed():
            if self.force:
                remove(self.target_path)

            self.repository.set_archive_metadata(self.archive_metadata)
            self._generate_archive()

    def _scan_path(self, backup_path: BackupPath) -> None:
        if backup_path.path in self.scan_cache:
            return
        self.scan_cache.add(backup_path.path)

        if self._is_path_excluded(backup_path.system_path):
            return

        self._scan_path_metadata(backup_path)
        if not backup_path.exists():
            return

        if backup_path.is_dir():
            self._scan_dir(backup_path)
        else:
            self.result.add(backup_path.system_path)

    def _scan_path_metadata(self, backup_path: BackupPath) -> None:
        if backup_path.path in self.archive_metadata:
            backup_path.archive_metadata = self.archive_metadata[backup_path.path]
            return

        if (parent := self._get_parent_path(backup_path)) is not None:
            self._scan_path_metadata(parent)

        if (stat_result := self._stat_path(backup_path.system_path)) is None:
            metadata = None
        else:
            metadata = self._generate_archive_metadata(backup_path.system_path, stat_result)

        backup_path.archive_metadata = metadata
        self.archive_metadata[backup_path.path] = metadata

    def _stat_path(self, path: Path) -> os.stat_result | None:
        if path in self.stat_cache:
            return self.stat_cache[path]

        stat_result = None
        try:
            stat_result = stat_path(path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
        else:
            if stat_result is not None and not self._is_supported_type(stat_result):
                print(f"File's type is not supported: {path}", file=sys.stderr)
            else:
                return stat_result
        finally:
            self.stat_cache[path] = stat_result

    def _get_parent_path(self, backup_path: BackupPath) -> BackupPath | None:
        if (parent := backup_path.get_parent()) is not None:
            return self._refresh_backup_path(parent)

    def _refresh_backup_path(self, backup_path: BackupPath) -> BackupPath:
        if backup_path.system_path in self.tracked_paths:
            return evolve(self.tracked_paths[backup_path.system_path])
        else:
            return backup_path

    def _generate_archive_metadata(self, path: Path, stat_result: os.stat_result) -> ArchiveMetadata:
        return ArchiveMetadata(
            group=self._resolve_system_group(stat_result.st_gid),
            mode=stat_result.st_mode,
            mtime_ns=stat_result.st_mtime_ns,
            path=self._generate_archive_path(path, stat_result.st_mode),
            size=stat_result.st_size,
            user=self._resolve_system_user(stat_result.st_uid)
        )

    def _scan_dir(self, backup_path: BackupPath) -> None:
        try:
            children = self._get_children_paths(backup_path)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
            return

        for child in children:
            self._scan_path(child)

        for child in children:
            if child.system_path not in self.result:
                return

        for child in children:
            self.result.discard(child.system_path)

        self.result.add(backup_path.system_path)

    def _get_children_paths(self, backup_path: BackupPath) -> list[BackupPath]:
        return [self._refresh_backup_path(c) for c in backup_path.get_children()]

    def _is_archive_changed(self) -> bool:
        return self.archive_metadata != self.repository.get_archive_metadata()

    def _generate_archive(self) -> None:
        self.result.add(Path(self.conf_dir.name))
        paths = "\n".join(sorted(os.fspath(p) for p in self.result))

        subprocess.run(["zip", "-@FSeory", "-P", self.ARCHIVE_PWD, self.target_path],
                       cwd=self.conf_dir.parent, input=paths, text=True)

        chstat(self.target_path)


@define(init=False)
class BackupPath:
    path: Path
    archive_metadata: ArchiveMetadata | None = field(init=False)
    system_path: Path = field(init=False)

    def __init__(self, path: Path):
        self.path = path
        self.archive_metadata = None
        self.system_path = expand_path(path)

    def __truediv__(self, other: BackupPath | StrPath) -> BackupPath:
        if isinstance(other, BackupPath):
            return BackupPath(self.path / other.path)
        else:
            return BackupPath(self.path / other)

    def __rtruediv__(self, other: StrPath) -> BackupPath:
        return BackupPath(other / self.path)

    def exists(self) -> bool:
        return self.archive_metadata is not None

    def get_children(self) -> list[BackupPath]:
        return [self / p.name
                for p in sorted(self.system_path.iterdir())]

    def get_parent(self) -> BackupPath | None:
        for path in (self.path, self.system_path):
            if path.parent != path.parent.parent:
                return BackupPath(path.parent)

    def is_dir(self) -> bool:
        return self.archive_metadata is not None and stat.S_ISDIR(self.archive_metadata.mode)


class RestoreHandler(BaseArchiveHandler):
    TMP_SUFFIX = ".backup-pro.tmp"

    def __init__(self, dry_run: bool = False, interactive: bool = False):
        super().__init__()
        self.dry_run: bool = dry_run
        self.interactive: bool = interactive
        self.repository: Repository = Repository()

        self.conf_dir: Path = self.repository.get_conf_dir()
        self.target_path: Path = self.repository.get_target_path()

        self.archive_file: zipfile.ZipFile = self._open_archive_file()

        self.archive_exclude_paths: set[Path] = {expand_path(p) for p in self.repository.get_archive_exclude_paths()}
        self.archive_exclude_paths.add(self.conf_dir)
        self.archive_exclude_paths.add(self.target_path)

        self.archive_exclude_patterns: list[Pattern[str]] = [re.compile(p)
                                                             for p in self.repository.get_archive_exclude_patterns()]

        self.archive_metadata: dict[Path, ArchiveMetadata] = {expand_path(k): v
                                                              for k, v in
                                                              self.repository.get_archive_metadata().items()}

        self.diff_checker: str | None = None
        self.inode_cache: set[tuple[int, int]] = set()
        self.restore_cache: set[Path] = set()
        self.system_dirs: set[Path] = set()
        self.tmp_root: Path | None = None
        tracked_paths = (self._scan_archive_info(RestorePath.from_tracked_path(tp))
                         for tp in self.repository.get_tracked_paths().values())
        self.tracked_paths = {rp.system_path: rp for rp in tracked_paths}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _scan_archive_info(self, restore_path: RestorePath) -> RestorePath:
        restore_path.archive_info = None
        restore_path.archive_metadata = self.archive_metadata.get(restore_path.system_path)
        if restore_path.archive_metadata is not None:
            try:
                restore_path.archive_info = self.archive_file.getinfo(restore_path.archive_metadata.path)
            except KeyError:
                pass
            else:
                restore_path.archive_metadata.mode = restore_path.archive_info.external_attr >> 16
                restore_path.archive_metadata.size = restore_path.archive_info.file_size

        return restore_path

    def _open_archive_file(self) -> zipfile.ZipFile:
        try:
            return zipfile.ZipFile(self.target_path)
        except Exception as e:
            raise BackupProException(f"Failed to open target file '{self.target_path}': {e}")

    def close(self) -> None:
        self.archive_file.close()

    def restore(self) -> None:
        self._detect_diff_checker()
        tmp_dir = tempfile.mkdtemp(prefix="backup-pro-data.")
        self.tmp_root = Path(tmp_dir)

        try:
            for restore_path in self.tracked_paths.values():
                self._restore_path(evolve(restore_path))
        finally:
            if self.diff_checker:
                remove(tmp_dir)

    def _detect_diff_checker(self):
        diff_checker = os.environ.get("DIFF_CHECKER")
        if diff_checker:
            if shutil.which(diff_checker):
                self.diff_checker = diff_checker
            else:
                raise BackupProException(
                    f"DIFF_CHECKER={diff_checker} is given but could not find the '{diff_checker}' executable.\n"
                    f"Please install '{diff_checker}' and make sure that it's in the '$PATH' variable.")

    def _restore_path(self, restore_path: RestorePath) -> None:
        if restore_path.system_path in self.restore_cache:
            return
        self.restore_cache.add(restore_path.system_path)

        if restore_path.strategy == BackupStrategy.BackupOnly or self._is_path_excluded(restore_path.system_path):
            return

        try:
            self._scan_system_metadata(restore_path)
            if not restore_path.exists_on_archive() or self._check_loop(restore_path):
                return
            elif restore_path.has_format_conflict():
                self._remove(restore_path)

            if self._should_restore_manually(restore_path):
                self._restore_manually(restore_path)
                return

            if restore_path.is_dir_on_archive():
                self._restore_dir(restore_path)
            else:
                self._restore_file(restore_path)

            self._chstat(restore_path)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def _scan_system_metadata(self, restore_path: RestorePath) -> None:
        if restore_path.scanned:
            return
        restore_path.scanned = True

        restore_path.system_stat_result = None
        try:
            stat_result = stat_path(restore_path.system_path)
        except FileNotFoundError:
            stat_result = None

        if stat_result is not None:
            if self._is_supported_type(stat_result):
                restore_path.system_stat_result = stat_result
            else:
                raise BackupProException(f"File's type is not supported: {restore_path.system_path}")

    def _check_loop(self, restore_path: RestorePath) -> bool:
        if restore_path.system_stat_result is None:
            return False

        key = (restore_path.system_stat_result.st_dev, restore_path.system_stat_result.st_ino)
        if key in self.inode_cache:
            return True
        else:
            self.inode_cache.add(key)
            return False

    def _remove(self, restore_path: RestorePath) -> None:
        print(f"[D] {restore_path.system_path}")
        if not self.dry_run:
            remove(restore_path.system_path, restore_path.system_stat_result)
            self.system_dirs.discard(restore_path.system_path)

        restore_path.set_removed()

    def _should_restore_manually(self, restore_path: RestorePath) -> bool:
        return self.interactive or restore_path.strategy == BackupStrategy.Manual

    def _restore_manually(self, restore_path: RestorePath) -> None:
        try:
            if not self._is_path_changed(restore_path):
                return

            tmp_path = self.tmp_root / PurePosixPath(restore_path.archive_path)
            print(f"[M] {tmp_path} {restore_path.system_path}")
            if not self.dry_run:
                self._extract_tmp_path(restore_path)
                if self.diff_checker:
                    self._check_diff(tmp_path, restore_path)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def _is_path_changed(self, restore_path: RestorePath) -> bool:
        try:
            self._scan_system_metadata(restore_path)
            if restore_path.is_dir_on_archive():
                return any(self._is_path_changed(c) for c in self._get_children_on_archive(restore_path))
            else:
                return restore_path.is_changed()
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
            return True

    def _extract_tmp_path(self, restore_path: RestorePath) -> None:
        try:
            self._extract_archive_path(restore_path.archive_info, self.tmp_root)
            if restore_path.is_dir_on_archive():
                for child in self._get_children_on_archive(restore_path):
                    self._extract_tmp_path(child)

            self._restore_tmp_metadata(restore_path)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def _extract_archive_path(self, archive_info: zipfile.ZipInfo, target_path: Path) -> None:
        if stat.S_ISLNK(archive_info.external_attr >> 16):
            target_path = target_path / PurePosixPath(archive_info.filename)
            link_target = self.archive_file.read(archive_info, self.ARCHIVE_PWDB)
            remove(target_path)
            os.symlink(link_target, target_path)
        else:
            self.archive_file.extract(archive_info, target_path, self.ARCHIVE_PWDB)

    def _restore_tmp_metadata(self, restore_path: RestorePath) -> None:
        chstat(
            path=self.tmp_root / PurePosixPath(restore_path.archive_path),
            mode=restore_path.archive_metadata.mode,
            uid=self._resolve_system_user(restore_path.archive_metadata.user),
            gid=self._resolve_system_group(restore_path.archive_metadata.group),
            mtime_ns=restore_path.archive_metadata.mtime_ns
        )

    def _check_diff(self, tmp_path: Path, restore_path: RestorePath) -> None:
        subprocess.run([self.diff_checker, tmp_path, restore_path.system_path])
        self._restore_metadata(restore_path)
        restore_path.reset_system_metadata()

    def _restore_metadata(self, restore_path: RestorePath) -> None:
        try:
            self._scan_system_metadata(restore_path)
            if restore_path.has_same_format():
                self._chstat(restore_path)
                if restore_path.is_dir_on_archive():
                    for child in self._get_children_on_archive(restore_path):
                        self._restore_metadata(child)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def _chstat(self, restore_path: RestorePath) -> None:
        if self.dry_run:
            return

        self._scan_system_metadata(restore_path)
        chstat(
            path=restore_path.system_path,
            mode=restore_path.archive_metadata.mode,
            uid=self._resolve_system_user(restore_path.archive_metadata.user),
            gid=self._resolve_system_group(restore_path.archive_metadata.group),
            mtime_ns=restore_path.archive_metadata.mtime_ns,
            stat_result=restore_path.system_stat_result
        )
        restore_path.reset_system_metadata()

    def _get_children_on_archive(self, restore_path: RestorePath) -> list[RestorePath]:
        children = sorted(c.name for c in zipfile.Path(self.archive_file, restore_path.archive_path).iterdir())
        return [self._refresh_restore_path(restore_path / c) for c in children]

    def _refresh_restore_path(self, restore_path: RestorePath) -> RestorePath:
        if restore_path.system_path in self.tracked_paths:
            return evolve(self.tracked_paths[restore_path.system_path])
        else:
            return self._scan_archive_info(restore_path)

    def _restore_dir(self, restore_path: RestorePath) -> None:
        prune_dir = False
        try:
            self._scan_system_metadata(restore_path)
            if not restore_path.exists_on_system():
                self._makedirs(restore_path)
                self._scan_system_metadata(restore_path)
            else:
                prune_dir = True

            children_on_archive = {rp.system_path: rp for rp in self._get_children_on_archive(restore_path)}
            if prune_dir:
                for child in self._get_children_on_system(restore_path):
                    if child.system_path not in children_on_archive:
                        self._prune_path(child)

            for child in children_on_archive.values():
                self._restore_path(child)
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def _makedirs(self, restore_path: RestorePath) -> None:
        if restore_path.system_path in self.system_dirs:
            return

        self._scan_system_metadata(restore_path)
        if not restore_path.exists_on_system():
            if (parent := self._get_parent(restore_path)) is not None:
                self._makedirs(parent)

            self._mkdir(restore_path)

        self.system_dirs.add(restore_path.system_path)

    def _get_parent(self, restore_path: RestorePath) -> RestorePath | None:
        if (parent := restore_path.get_parent()) is not None:
            return self._refresh_restore_path(parent)

    def _mkdir(self, restore_path: RestorePath) -> None:
        print(f"[C] {restore_path.system_path}")
        if not self.dry_run:
            if restore_path.archive_metadata is None:
                mkdir(restore_path.system_path)
            else:
                mkdir(
                    path=restore_path.system_path,
                    mode=restore_path.archive_metadata.mode,
                    uid=self._resolve_system_user(restore_path.archive_metadata.user),
                    gid=self._resolve_system_group(restore_path.archive_metadata.group),
                    mtime_ns=restore_path.archive_metadata.mtime_ns
                )
            restore_path.reset_system_metadata()

    def _get_children_on_system(self, restore_path: RestorePath) -> list[RestorePath]:
        return [self._refresh_restore_path(rp) for rp in restore_path.get_children_on_system()]

    def _prune_path(self, restore_path: RestorePath) -> bool:
        if restore_path.system_path in self.tracked_paths or self._is_path_excluded(restore_path.system_path):
            return False

        try:
            self._scan_system_metadata(restore_path)
            if restore_path.exists_on_archive():
                return False
            if not restore_path.exists_on_system():
                return True

            if restore_path.is_dir_on_system():
                children = [self._prune_path(c) for c in self._get_children_on_system(restore_path)]
                if all(children):
                    self._remove(restore_path)
                    return True
                else:
                    return False
            else:
                self._remove(restore_path)
                return True
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
            return False

    def _restore_file(self, restore_path: RestorePath) -> None:
        try:
            self._scan_system_metadata(restore_path)
            if not restore_path.exists_on_system():
                if (parent := self._get_parent(restore_path)) is not None:
                    self._makedirs(parent)
            elif not restore_path.is_changed():
                return

            print(f"[C] {restore_path.system_path}")
            if not self.dry_run:
                if stat.S_ISLNK(restore_path.archive_metadata.mode):
                    target = self.archive_file.read(restore_path.archive_info, self.ARCHIVE_PWDB)
                    self._remove(restore_path)
                    os.symlink(target, restore_path.system_path)
                else:
                    target = restore_path.system_path.with_name(restore_path.system_path.name + self.TMP_SUFFIX)
                    try:
                        with self.archive_file.open(restore_path.archive_info, pwd=self.ARCHIVE_PWDB) as src:
                            with open(target, "bw") as dst:
                                shutil.copyfileobj(src, dst)

                        remove(restore_path.system_path, restore_path.system_stat_result)
                        shutil.move(target, restore_path.system_path)
                    except Exception as e:
                        remove(target)
                        raise e

                restore_path.reset_system_metadata()
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}", file=sys.stderr)

    def restore_conf(self, force: bool = False) -> None:
        if not force and os.path.exists(self.conf_dir):
            return

        conf_path = f"{CONF_HOLDER}/{CONF_FILE}"
        state_path = f"{CONF_HOLDER}/{STATE_FILE}"

        try:
            conf = self.archive_file.read(conf_path, self.ARCHIVE_PWDB)
            conf = json_loads(conf)
            state = self.archive_file.read(state_path, self.ARCHIVE_PWDB)
            state = json_loads(state)
            self.repository.load(conf, state)
        except Exception as e:
            raise BackupProException(f"Failed to read target file '{self.archive_file.filename}': {e}")

        self._restore_conf_dir()

    def _restore_conf_dir(self) -> None:
        print(f"[C] {self.conf_dir}")
        if not self.dry_run:
            members = (i for i in self.archive_file.infolist()
                       if PurePosixPath(i.filename).is_relative_to(CONF_HOLDER))

            for member in members:
                try:
                    self._extract_archive_path(member, self.conf_dir.parent)
                    chstat(
                        path=self.conf_dir.parent / PurePosixPath(member.filename),
                        mode=member.external_attr >> 16,
                        mtime_ns=int(datetime(*member.date_time).timestamp() * 10 ** 9)
                    )
                except Exception as e:
                    print(f"{e.__class__.__name__}: {e}", file=sys.stderr)


@define(eq=True, order=True)
class RestorePath:
    system_path: Path
    strategy: BackupStrategy
    archive_info: zipfile.ZipInfo | None = field(default=None, eq=False, order=False)
    archive_metadata: ArchiveMetadata | None = field(default=None, eq=False, order=False)
    scanned: bool = field(default=False, eq=False, init=False, order=False)
    system_stat_result: os.stat_result | None = field(default=None, eq=False, init=False, order=False)

    def __truediv__(self, other: RestorePath | StrPath) -> RestorePath:
        if isinstance(other, RestorePath):
            return RestorePath(self.system_path / other.system_path, other.strategy)
        else:
            return RestorePath(self.system_path / other, self.strategy)

    def __rtruediv__(self, other: StrPath) -> RestorePath:
        return RestorePath(other / self.system_path, self.strategy)

    @property
    def archive_path(self) -> str:
        return self.archive_info.filename

    def exists_on_archive(self) -> bool:
        return self.archive_info is not None

    def exists_on_system(self) -> bool:
        return self.system_stat_result is not None

    @classmethod
    def from_tracked_path(cls, tracked_path: TrackedPath) -> RestorePath:
        return RestorePath(expand_path(tracked_path.path), tracked_path.strategy)

    def get_children_on_system(self) -> list[RestorePath]:
        return [RestorePath(c, self.strategy) for c in sorted(self.system_path.iterdir())]

    def get_parent(self) -> RestorePath | None:
        if self.system_path.parent != self.system_path.parent.parent:
            return RestorePath(self.system_path.parent, BackupStrategy.BackupOnly)

    def has_format_conflict(self) -> bool:
        return self.archive_metadata is not None \
            and self.system_stat_result is not None \
            and (stat.S_IFMT(self.archive_metadata.mode) != stat.S_IFMT(self.system_stat_result.st_mode))

    def has_same_format(self) -> bool:
        return self.archive_metadata is not None \
            and self.system_stat_result is not None \
            and (stat.S_IFMT(self.archive_metadata.mode) == stat.S_IFMT(self.system_stat_result.st_mode))

    def is_changed(self) -> bool:
        return self.archive_metadata is None \
            or self.system_stat_result is None \
            or stat.S_ISDIR(self.archive_metadata.mode) \
            or self.archive_metadata.is_data_different(self.system_stat_result)

    def is_dir_on_archive(self) -> bool:
        return self.archive_info.is_dir() if self.archive_info is not None else False

    def is_dir_on_system(self) -> bool:
        return stat.S_ISDIR(self.system_stat_result.st_mode) if self.system_stat_result is not None else False

    def reset_system_metadata(self) -> None:
        self.scanned = False
        self.system_stat_result = None

    def set_removed(self) -> None:
        self.system_stat_result = None
