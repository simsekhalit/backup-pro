#!/usr/bin/env python3
from __future__ import annotations

from os import getcwd as _getcwd

DEFAULT_CONF_DIR = _getcwd()
DEFAULT_TARGET_DIR = _getcwd()

CONF_FILE = "conf.json"
CONF_HOLDER = ".backup-pro-conf"
INDEX_SNAPSHOTS_DIR = "index_snapshots"
STATE_FILE = "state.json"
TARGET_FILE = "backup-pro-data.zip"
