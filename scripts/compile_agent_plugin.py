#!/usr/bin/env python3
"""Render the portable Agent Plugins manifest from Forge's compatibility metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CORE_FIELDS = ("name", "version", "description", "author", "homepage", "repository", "license", "keywords")
OPENAI_FIELDS = ("id", "interface", "apps", "mcpServers", "hooks")


def render(repo: Path) -> str:
    source = repo / "plugins/forge/.codex-plugin/plugin.json"
    legacy = json.loads(source.read_text(encoding="utf-8"))
    manifest = {"$schema": SCHEMA}
    manifest.update({field: legacy[field] for field in CORE_FIELDS if field in legacy})
    manifest["extensions"] = {
        "com.openai": {field: legacy[field] for field in OPENAI_FIELDS if field in legacy}
    }
    return json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = args.repo / "plugins/forge/plugin.json"
    expected = render(args.repo)
    if args.write:
        target.write_text(expected, encoding="utf-8")
    elif not target.is_file() or target.read_text(encoding="utf-8") != expected:
        print("Portable plugin manifest is stale; run python3 scripts/compile_agent_plugin.py --write")
        return 1
    print("Portable plugin manifest is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
