#!/usr/bin/env python3
"""Forge eval harness — the evidence layer.

Two modes:

  python3 evals/run.py            Static prompt-quality checks (no API key, runs in CI).
  python3 evals/run.py --judge    Behavioral eval: run each case against the Claude API,
                                   then score the output with an LLM judge (needs
                                   ANTHROPIC_API_KEY).

Static mode is the reproducible, free signal that gates CI. Judge mode is the gold
standard — it proves an agent's system prompt actually produces the behavior its
description promises — but it costs API calls, so you run it locally before a release.

Zero third-party dependencies: stdlib only (urllib for the judge calls).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "forge"
AGENTS = PLUGIN / "agents"
SKILLS = PLUGIN / "skills"
COMMANDS = PLUGIN / "commands"

VALID_MODELS = {"sonnet", "opus", "haiku", "fable", "inherit"}
VALID_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
API_URL = "https://api.anthropic.com/v1/messages"
JUDGE_MODEL = os.environ.get("FORGE_JUDGE_MODEL", "claude-opus-4-8")


# --------------------------------------------------------------------------- #
# Frontmatter parsing (no YAML dependency — these files use simple key: scalars)
# --------------------------------------------------------------------------- #

def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). Values are raw strings; multi-line folded
    scalars (`>-`) are joined. Good enough for our well-formed files."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip("\n")
    body = text[end + 4 :]
    fm: dict[str, str] = {}
    key = None
    for line in fm_block.splitlines():
        m = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            key = m.group(1)
            val = m.group(2).strip()
            fm[key] = "" if val in (">-", ">", "|", "|-") else val
        elif key and line.strip():
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, body


# --------------------------------------------------------------------------- #
# Static prompt-quality checks
# --------------------------------------------------------------------------- #

class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.warned = 0

    def check(self, ok: bool, label: str, hard: bool = True) -> None:
        if ok:
            self.passed += 1
        elif hard:
            self.failed += 1
            print(f"  ✗ {label}")
        else:
            self.warned += 1
            print(f"  ⚠ {label}")


def check_agents(r: Report) -> None:
    print("\nAgents — prompt quality")
    for f in sorted(AGENTS.glob("*.md")):
        fm, body = split_frontmatter(f.read_text())
        name = f.stem
        desc = fm.get("description", "")
        r.check(bool(fm.get("name")), f"{name}: has name")
        r.check(40 <= len(desc) <= 1024, f"{name}: description length sane ({len(desc)})")
        r.check(desc.lower().startswith("use "), f"{name}: description starts with a trigger ('Use …')", hard=False)
        r.check("example" in desc.lower() or "e.g." in desc.lower(),
                f"{name}: description gives an example trigger", hard=False)
        model = fm.get("model", "inherit")
        r.check(model in VALID_MODELS or model.startswith("claude-"), f"{name}: valid model '{model}'")
        if "color" in fm:
            r.check(fm["color"] in VALID_COLORS, f"{name}: valid color '{fm['color']}'")
        # Read-only roles must not carry Edit/Write.
        tools = fm.get("tools", "")
        readonly = any(k in name for k in ("review", "audit", "debugg", "architect", "incident", "docs", "database", "api-design", "performance", "dependency", "tech-lead", "archaeolog"))
        if readonly:
            r.check("Edit" not in tools and "Write" not in tools,
                    f"{name}: read-only agent has no Edit/Write tool")
        # Body should give structure the model can follow.
        r.check(bool(re.search(r"(?im)^##?\s", body)) or len(body) > 400,
                f"{name}: body has structured guidance")


def check_skills(r: Report) -> None:
    print("\nSkills — prompt quality")
    for d in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
        f = d / "SKILL.md"
        if not f.exists():
            r.check(False, f"{d.name}: missing SKILL.md")
            continue
        fm, _ = split_frontmatter(f.read_text())
        desc = fm.get("description", "")
        r.check(fm.get("name") == d.name, f"{d.name}: name matches directory")
        r.check(40 <= len(desc) <= 1024, f"{d.name}: description length sane ({len(desc)})")
        r.check(desc.lower().startswith("use when") or "use when" in desc.lower(),
                f"{d.name}: description is situational ('use when …')", hard=False)


def check_commands(r: Report) -> None:
    print("\nCommands — prompt quality")
    for f in sorted(COMMANDS.glob("*.md")):
        fm, body = split_frontmatter(f.read_text())
        name = f.stem
        r.check(bool(fm.get("description")), f"{name}: has description")
        if re.search(r"\$ARGUMENTS|\$\d", body):
            r.check("argument-hint" in fm, f"{name}: declares argument-hint for its args", hard=False)
        if re.search(r"!`", body):
            r.check("allowed-tools" in fm, f"{name}: declares allowed-tools for its bash injection")


def run_static() -> int:
    r = Report()
    check_agents(r)
    check_skills(r)
    check_commands(r)
    total = r.passed + r.failed + r.warned
    print(f"\nStatic eval: {r.passed}/{total} passed, {r.warned} warnings, {r.failed} failures")
    if r.failed:
        print("❌ Static eval failed.")
        return 1
    print("✅ Static eval passed.")
    return 0


# --------------------------------------------------------------------------- #
# Behavioral eval (LLM judge)
# --------------------------------------------------------------------------- #

def call_claude(model: str, system: str, user: str, api_key: str, max_tokens: int = 2048) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def load_agent_prompt(target: str) -> tuple[str, str]:
    """Return (system_prompt_body, model_alias) for an agent target."""
    f = AGENTS / f"{target}.md"
    fm, body = split_frontmatter(f.read_text())
    model = fm.get("model", "sonnet")
    alias = {"sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8", "haiku": "claude-haiku-4-5"}.get(model, "claude-sonnet-4-6")
    return body.strip(), alias


def run_judge() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set — cannot run judge mode. (Static mode needs no key.)")
        return 2
    cases_file = REPO / "evals" / "cases.jsonl"
    cases = [json.loads(line) for line in cases_file.read_text().splitlines() if line.strip()]
    passed = 0
    for c in cases:
        if c.get("type") != "agent":
            continue  # judge mode currently scores agent cases
        system, model = load_agent_prompt(c["target"])
        try:
            output = call_claude(model, system, c["prompt"], api_key)
        except urllib.error.HTTPError as e:
            print(f"  ✗ {c['id']}: API error {e.code}")
            continue
        rubric = "\n".join(f"- {x}" for x in c["criteria"])
        judge_system = (
            "You are a strict evaluator. Score the RESPONSE against each CRITERION. "
            'Reply with ONLY JSON: {"met": <int>, "total": <int>, "pass": <bool>, "notes": "<one line>"}.'
        )
        judge_user = f"## TASK\n{c['prompt']}\n\n## CRITERIA\n{rubric}\n\n## RESPONSE\n{output}"
        verdict_raw = call_claude(JUDGE_MODEL, judge_system, judge_user, api_key, max_tokens=512)
        m = re.search(r"\{.*\}", verdict_raw, re.DOTALL)
        if not m:
            print(f"  ✗ {c['id']}: judge returned no JSON")
            continue
        v = json.loads(m.group(0))
        ok = bool(v.get("pass"))
        passed += ok
        mark = "✓" if ok else "✗"
        print(f"  {mark} {c['id']} [{c['target']}] {v.get('met')}/{v.get('total')} — {v.get('notes','')}")
    print(f"\nJudge eval: {passed} cases passed")
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Forge eval harness")
    ap.add_argument("--judge", action="store_true", help="run the LLM-judge behavioral eval (needs ANTHROPIC_API_KEY)")
    args = ap.parse_args()
    return run_judge() if args.judge else run_static()


if __name__ == "__main__":
    sys.exit(main())
