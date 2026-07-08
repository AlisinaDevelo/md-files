#!/usr/bin/env python3
"""Generate Forge's human and machine-readable component catalog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "forge"


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end].strip()
    body = text[end + 4 :]
    out: dict[str, str] = {}
    key: str | None = None
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match and not line.startswith(" "):
            key = match.group(1)
            value = match.group(2).strip()
            out[key] = "" if value in {">-", ">", "|", "|-"} else value.strip('"')
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out, body


def risk_for(kind: str, frontmatter: dict[str, str]) -> str:
    tools = frontmatter.get("tools", "") + " " + frontmatter.get("allowed-tools", "")
    name = frontmatter.get("name", "")
    desc = frontmatter.get("description", "").lower()
    if "security" in name or "security" in desc or "threat" in name:
        return "security-sensitive"
    if any(token in tools for token in ("Write", "Edit", "Bash(gh", "Bash(git", "Bash")):
        return "critical" if any(token in tools for token in ("Write", "Edit", "gh issue", "git")) else "safe"
    if kind in {"agent", "skill"} and tools:
        return "safe"
    return "none"


def component_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    specs = [
        ("agent", PLUGIN / "agents", "*.md"),
        ("skill", PLUGIN / "skills", "SKILL.md"),
        ("command", PLUGIN / "commands", "*.md"),
    ]
    for kind, root, pattern in specs:
        for path in sorted(root.glob(f"**/{pattern}")):
            fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
            if kind == "skill":
                component_id = path.parent.name
            else:
                component_id = path.stem
            rows.append(
                {
                    "id": component_id,
                    "kind": kind,
                    "path": str(path.relative_to(REPO)),
                    "description": fm.get("description", "").strip(),
                    "model": fm.get("model", ""),
                    "risk": risk_for(kind, fm),
                }
            )
    return rows


def write_catalog(rows: list[dict[str, str]]) -> None:
    data_dir = REPO / "data"
    data_dir.mkdir(exist_ok=True)
    payload = {
        "version": 1,
        "total": len(rows),
        "components": rows,
    }
    (data_dir / "catalog.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1

    lines = [
        "# Forge Catalog",
        "",
        "Generated from the Forge plugin source. Do not hand-edit component rows; run",
        "`python3 scripts/generate_catalog.py` after changing agents, skills, or commands.",
        "",
        "## Summary",
        "",
        "| Kind | Count |",
        "|------|------:|",
    ]
    for kind in ("agent", "skill", "command"):
        lines.append(f"| {kind}s | {counts.get(kind, 0)} |")
    lines += [
        f"| total | {len(rows)} |",
        "",
        "## Components",
        "",
        "| id | kind | risk | model | path | description |",
        "|----|------|------|-------|------|-------------|",
    ]
    for row in rows:
        command = "/" if row["kind"] == "command" else ""
        model = row["model"] or "-"
        desc = row["description"].replace("|", "\\|")
        lines.append(
            f"| `{command}{row['id']}` | {row['kind']} | {row['risk']} | {model} | "
            f"[{row['path']}]({row['path']}) | {desc} |"
        )
    lines.append("")
    (REPO / "CATALOG.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()

    before = {}
    for rel in ("CATALOG.md", "data/catalog.json"):
        path = REPO / rel
        before[rel] = path.read_text(encoding="utf-8") if path.exists() else None

    rows = component_rows()
    write_catalog(rows)

    if args.check:
        stale = []
        for rel, old in before.items():
            new = (REPO / rel).read_text(encoding="utf-8")
            if old != new:
                stale.append(rel)
        if stale:
            print("Catalog files were stale: " + ", ".join(stale), file=sys.stderr)
            return 1
    print(f"Generated catalog for {len(rows)} Forge components.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
