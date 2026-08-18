#!/usr/bin/env python3
"""Run the Forge A2A StreamResponse evidence adapter from the repository root."""

from pathlib import Path
import runpy


TARGET = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "forge"
    / "skills"
    / "orchestration"
    / "scripts"
    / "forge-a2a-stream.py"
)


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
