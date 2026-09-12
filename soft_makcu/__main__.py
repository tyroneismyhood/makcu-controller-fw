"""python -m soft_makcu — THE one-command Soft Lab launch (never flashes)."""

from __future__ import annotations

import sys

from .lab_ui import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
