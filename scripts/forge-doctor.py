#!/usr/bin/env python3
"""Convenience entry point for the bundled Forge Doctor skill script."""

from __future__ import annotations

import runpy
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "forge"
    / "skills"
    / "doctor"
    / "scripts"
    / "forge-doctor.py"
)


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
