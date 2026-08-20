#!/usr/bin/env python3
"""Run the fenced Forge gh-aw GitHub provider worker from the repository root."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "plugins/forge/skills/orchestration/scripts/forge-gh-aw-provider.py"
    ),
    run_name="__main__",
)
