#!/usr/bin/env python3
"""Run Forge's offline identity and delegated-authority verifier."""

import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "plugins/forge/skills/policy/scripts/forge-authority.py"),
    run_name="__main__",
)
