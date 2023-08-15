#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import AnyStr

if sys.implementation.name == "cpython":
    try:
        import ujson
    except ImportError:
        import json

        ujson = None
else:
    import json

    ujson = None

__all__ = [
    "AnyPath",
    "BackupProException",
    "chmod",
    "chown",
    "chstat",
    "expand_path",
    "FdOrAnyPath",
    "get_real_gid",
    "get_real_uid",
    "json_dump",
    "json_dumps",
    "json_load",
    "json_loads",
    "mkdir",
    "read",
    "remove",
    "sanitize_path",
    "stat_path",
    "strip_anchor",
    "StrPath",
    "touch",
    "utime",
    "write"
]

StrPath = os.PathLike[str] | str
AnyPath = AnyStr | os.PathLike[bytes] | os.PathLike[str]
FdOrAnyPath = AnyPath | int


class BackupProException(Exception):
    pass


def chmod(path: FdOrAnyPath, mode: int, stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        stat_result = stat_path(path)

    if mode & 0o7777 != stat_result.st_mode & 0o7777:
        if isinstance(path, int):
            os.chmod(path, mode)
        else:
            os.chmod(path, mode, follow_symlinks=False)


def chown(path: FdOrAnyPath, uid: int = None, gid: int = None, stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        stat_result = stat_path(path)

    if uid is None:
        uid = get_real_uid()

    if gid is None:
        gid = get_real_gid()

    if stat_result.st_uid != uid or stat_result.st_gid != gid:
        if isinstance(path, int):
            os.chown(path, uid, gid)
        else:
            os.chown(path, uid, gid, follow_symlinks=False)


def chstat(path: FdOrAnyPath, mode: int = None, uid: int = None, gid: int = None, mtime_ns: int = None,
           stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        stat_result = stat_path(path)

    if mode is not None:
        chmod(path, mode, stat_result)

    chown(path, uid, gid, stat_result)

    if mtime_ns is not None:
        utime(path, mtime_ns, stat_result)


def expand_path(path: StrPath) -> Path:
    return Path(os.path.expandvars(path)).absolute()


def get_real_gid() -> int:
    return int(os.environ["SUDO_GID"]) if "SUDO_GID" in os.environ else os.getgid()


def get_real_uid() -> int:
    return int(os.environ["SUDO_UID"]) if "SUDO_UID" in os.environ else os.getuid()


def json_dump(data: dict, path: FdOrAnyPath, pretty: bool = False) -> None:
    data = json_dumps(data, pretty)
    write(path, "w", data)
    chown(path)


def json_dumps(data: dict, pretty: bool = False) -> str:
    if ujson is not None:
        if pretty:
            return ujson.dumps(data, escape_forward_slashes=False, indent=2, sort_keys=True)
        else:
            return ujson.dumps(data, escape_forward_slashes=False)
    else:
        if pretty:
            return json.dumps(data, indent=2, sort_keys=True)
        else:
            return json.dumps(data)


def json_load(path: FdOrAnyPath) -> dict:
    data = read(path, "r")
    return json_loads(data)


def json_loads(data: AnyStr) -> dict:
    if ujson is not None:
        return ujson.loads(data)
    else:
        return json.loads(data)


def mkdir(path: AnyPath, mode: int = None, uid: int = None, gid: int = None, mtime_ns: int = None) -> None:
    try:
        stat_result = stat_path(path)
    except FileNotFoundError:
        stat_result = None

    if stat_result is not None and not stat.S_ISDIR(stat_result.st_mode):
        os.remove(path)
        stat_result = None

    if stat_result is None:
        if mode is None:
            os.mkdir(path)
        else:
            os.mkdir(path, mode)

    chstat(path, mode, uid, gid, mtime_ns, stat_result)


def read(path: FdOrAnyPath, mode: str) -> AnyStr:
    with open(path, mode) as f:
        return f.read()


def remove(path: AnyPath, stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        try:
            stat_result = stat_path(path)
        except FileNotFoundError:
            stat_result = None

    if stat_result is not None:
        if stat.S_ISDIR(stat_result.st_mode):
            shutil.rmtree(path)
        else:
            os.remove(path)


def sanitize_path(path: StrPath) -> Path:
    if not isinstance(path, Path):
        path = Path(path)
    system_path = Path(os.path.expandvars(path))
    return path if path != system_path else path.absolute()


def stat_path(path: FdOrAnyPath) -> os.stat_result:
    if isinstance(path, int):
        return os.stat(path)
    else:
        return os.stat(path, follow_symlinks=False)


def strip_anchor(path: StrPath) -> Path:
    if not isinstance(path, Path):
        path = Path(path)

    if path.anchor:
        return path.relative_to(path.anchor)
    else:
        return path


def touch(path: FdOrAnyPath, mode: int = None, uid: int = None, gid: int = None, mtime_ns: int = None,
          stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        try:
            stat_result = stat_path(path)
        except FileNotFoundError:
            stat_result = None

    if stat_result is None:
        with open(path, "a") as f:
            chstat(f.fileno(), mode, uid, gid, mtime_ns)
    else:
        chstat(path, mode, uid, gid, mtime_ns, stat_result)


def utime(path: FdOrAnyPath, mtime_ns: int, stat_result: os.stat_result = None) -> None:
    if stat_result is None:
        stat_result = stat_path(path)

    if (stat_result.st_mtime_ns // 10 ** 9) != (mtime_ns // 10 ** 9):
        if isinstance(path, int):
            os.utime(path, ns=(mtime_ns, mtime_ns))
        else:
            os.utime(path, ns=(mtime_ns, mtime_ns), follow_symlinks=False)


def write(path: FdOrAnyPath, mode: str, data: AnyStr, newline_at_eof: bool = True) -> None:
    with open(path, mode) as f:
        f.write(data)

        if newline_at_eof and data and data[-1] != "\n":
            f.write("\n")

        f.flush()
