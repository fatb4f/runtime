#!/usr/bin/env python3
"""Repository-relative entrypoint for the browserless workbook adapter."""

from __future__ import annotations

import sys
from pathlib import Path

WORKBOOK_ROOT = Path(__file__).resolve().parent
SRC = WORKBOOK_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from context_workbook.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
