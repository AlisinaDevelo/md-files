#!/usr/bin/env python3
"""Convenience entry point for Forge contribution checks."""

from __future__ import annotations

import runpy
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "plugins/forge/skills/open-source-contribution/scripts/forge-contribute.py"

if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
