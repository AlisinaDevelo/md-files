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
CAPABILITIES = REPO / "data" / "capabilities.json"
COMPONENT_ORDER = {"agent": 0, "skill": 1, "command": 2}


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
    if CAPABILITIES.is_file():
        data = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
        rows = [
            {
                "id": component["id"],
                "kind": component["kind"],
                "path": component["source"],
                "description": component["frontmatter"].get("description", "").strip(),
                "model": component["frontmatter"].get("model", ""),
                "risk": component["risk"],
            }
            for component in data["components"]
        ]
        return sorted(rows, key=lambda row: (COMPONENT_ORDER[row["kind"]], row["path"]))
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


def render_catalog(rows: list[dict[str, str]]) -> tuple[str, str]:
    payload = {
        "version": 1,
        "total": len(rows),
        "components": rows,
    }
    json_text = json.dumps(payload, indent=2) + "\n"

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
    return "\n".join(lines), json_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args()

    rows = component_rows()
    catalog_text, json_text = render_catalog(rows)
    rendered = {
        "CATALOG.md": catalog_text,
        "data/catalog.json": json_text,
    }

    if args.check:
        stale = [
            rel
            for rel, expected in rendered.items()
            if not (REPO / rel).is_file()
            or (REPO / rel).read_text(encoding="utf-8") != expected
        ]
        if stale:
            print("Catalog files were stale: " + ", ".join(stale), file=sys.stderr)
            return 1
        print(f"Catalog is current for {len(rows)} Forge components.")
        return 0

    (REPO / "data").mkdir(exist_ok=True)
    for rel, content in rendered.items():
        (REPO / rel).write_text(content, encoding="utf-8")
    print(f"Generated catalog for {len(rows)} Forge components.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
