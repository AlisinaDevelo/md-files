#!/usr/bin/env python3
"""Convenience entry point for the Forge GitHub task-ledger backend."""

from __future__ import annotations

import runpy
from pathlib import Path


TARGET = Path(__file__).resolve().parents[1] / "plugins/forge/skills/task-ledger/scripts/forge-tasks.py"


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
