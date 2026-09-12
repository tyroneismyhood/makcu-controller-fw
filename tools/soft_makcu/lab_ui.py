#!/usr/bin/env python3
"""Launcher: python tools/soft_makcu/lab_ui.py → soft_makcu.lab_ui.main()."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from soft_makcu.lab_ui import main

if __name__ == "__main__":
    raise SystemExit(main())
