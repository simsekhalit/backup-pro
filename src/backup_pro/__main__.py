#!/usr/bin/env python3
from __future__ import annotations

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))
