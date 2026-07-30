#!/usr/bin/env python3
"""Plan and inspect stacked GitHub pull requests without hiding git operations."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

MANIFEST_VERSION = 1
DEFAULT_MANIFEST = Path(".forge/stack.json")
PROVIDERS = {"github", "vanilla", "graphite", "aviator", "sapling", "ghstack"}


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("version") != MANIFEST_VERSION:
        errors.append(f"version must be {MANIFEST_VERSION}")

    trunk = data.get("trunk")
    remote = data.get("remote")
    provider = data.get("provider", "github")
    branches = data.get("branches")
    if not isinstance(trunk, str) or not trunk.strip():
        errors.append("trunk must be a non-empty string")
    if not isinstance(remote, str) or not remote.strip():
        errors.append("remote must be a non-empty string")
    if provider not in PROVIDERS:
        errors.append(f"provider must be one of {', '.join(sorted(PROVIDERS))}")
    if not isinstance(branches, list):
        return [*errors, "branches must be a list"]

    known = {trunk} if isinstance(trunk, str) else set()
    seen: set[str] = set()
    for index, branch in enumerate(branches, start=1):
        if not isinstance(branch, dict):
            errors.append(f"branch {index} must be an object")
            continue
        name = branch.get("name")
        parent = branch.get("parent")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"branch {index} has no valid name")
            continue
        if name == trunk:
            errors.append(f"branch {name!r} cannot be the trunk")
        if name in seen:
            errors.append(f"duplicate branch {name!r}")
        if parent == name:
            errors.append(f"branch {name!r} cannot parent itself")
        elif parent not in known:
            errors.append(f"branch {name!r} has unknown parent {parent!r}")
        pr = branch.get("pr")
        if pr is not None and (not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0):
            errors.append(f"branch {name!r} has invalid PR number")
        seen.add(name)
        known.add(name)
    return errors


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def ref_exists(repo: Path, ref: str) -> bool:
    return run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def inspect_repo(
    data: dict[str, Any], repo: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    errors = validate_manifest(data)
    rows: list[dict[str, Any]] = []
    if errors:
        return rows, errors

    trunk = data["trunk"]
    if not ref_exists(repo, trunk):
        errors.append(f"trunk {trunk!r} is missing from the local repository")

    for branch in data["branches"]:
        name = branch["name"]
        parent = branch["parent"]
        row = {
            "name": name,
            "parent": parent,
            "pr": branch.get("pr"),
            "exists": ref_exists(repo, name),
            "parent_exists": ref_exists(repo, parent),
            "parent_is_ancestor": False,
            "commits": 0,
            "files": 0,
        }
        if not row["exists"]:
            errors.append(f"branch {name!r} is missing from the local repository")
        if not row["parent_exists"]:
            errors.append(f"parent {parent!r} for {name!r} is missing")
        if row["exists"] and row["parent_exists"]:
            ancestor = run_git(repo, "merge-base", "--is-ancestor", parent, name)
            row["parent_is_ancestor"] = ancestor.returncode == 0
            if not row["parent_is_ancestor"]:
                errors.append(f"parent {parent!r} is not an ancestor of {name!r}")
            count = run_git(repo, "rev-list", "--count", f"{parent}..{name}")
            if count.returncode == 0:
                row["commits"] = int(count.stdout.strip() or 0)
            files = run_git(repo, "diff", "--name-only", parent, name)
            if files.returncode == 0:
                row["files"] = len([line for line in files.stdout.splitlines() if line])
            if row["commits"] == 0:
                errors.append(f"branch {name!r} has no commits beyond {parent!r}")
        rows.append(row)
    return rows, errors


def q(value: str) -> str:
    return shlex.quote(value)


def submission_plan(data: dict[str, Any]) -> list[str]:
    remote = data["remote"]
    commands: list[str] = []
    for branch in data["branches"]:
        name = branch["name"]
        parent = branch["parent"]
        commands.append(f"git push --set-upstream {q(remote)} {q(name)}")
        if branch.get("pr"):
            commands.append(f"gh pr edit {branch['pr']} --base {q(parent)}")
        else:
            commands.append(
                f"gh pr create --base {q(parent)} --head {q(name)} --draft --fill"
            )
    return commands


def restack_plan(data: dict[str, Any]) -> list[str]:
    remote = data["remote"]
    commands: list[str] = []
    for branch in data["branches"]:
        name = branch["name"]
        parent = branch["parent"]
        commands.extend(
            [
                f"git switch {q(name)}",
                f"git rebase {q(parent)}",
                f"git push --force-with-lease {q(remote)} {q(name)}",
            ]
        )
    return commands


def adapter_plan(data: dict[str, Any], action: str, tool: str) -> list[str]:
    if tool == "github":
        plans = {
            "submit": ["gh stack submit"],
            "restack": ["gh stack rebase", "gh stack push"],
            "land": ["gh stack merge --yes --squash"],
        }
        return plans[action]
    if tool == "vanilla":
        if action == "land":
            raise ValueError("vanilla landing is intentionally planned one PR at a time")
        return submission_plan(data) if action == "submit" else restack_plan(data)
    if tool == "graphite":
        if action == "submit":
            return ["gt submit --stack"]
        if action == "land":
            return ["gt merge"]
        return ["gt sync", "gt restack", "gt submit --stack"]
    if tool == "aviator":
        plans = {
            "submit": ["av pr"],
            "restack": ["av restack", "av pr"],
            "land": ["av pr queue"],
        }
        return plans[action]
    if tool == "sapling":
        if action == "submit":
            return ["sl pr submit --stack"]
        if action == "land":
            raise ValueError("Sapling landing depends on the repository's GitHub policy")
        return ["sl pull", "sl rebase --restack", "sl pr submit --stack"]
    if tool == "ghstack":
        plans = {
            "submit": ["ghstack"],
            "restack": ["ghstack"],
            "land": ["ghstack land"],
        }
        return plans[action]
    raise ValueError(f"unsupported tool: {tool}")


def branch_label(branch: dict[str, Any], current: bool = False) -> str:
    pr = branch.get("pr")
    label = f"#{pr}" if pr else f"`{branch['name']}`"
    return f"**{label}**" if current else label


def pr_body(data: dict[str, Any], branch_name: str) -> str:
    branches = data["branches"]
    positions = {branch["name"]: index for index, branch in enumerate(branches)}
    if branch_name not in positions:
        raise ValueError(f"branch {branch_name!r} is not in the stack")
    index = positions[branch_name]
    current = branches[index]
    previous = branch_label(branches[index - 1]) if index > 0 else f"`{data['trunk']}`"
    following = (
        branch_label(branches[index + 1]) if index + 1 < len(branches) else "top"
    )

    rows = []
    for position, branch in enumerate(branches, start=1):
        rows.append(
            f"| {position} | {branch_label(branch, branch['name'] == branch_name)} | "
            f"`{branch['parent']}` |"
        )
    return "\n".join(
        [
            "<!-- forge-stack:v1 -->",
            f"## Stack position: {index + 1} of {len(branches)}",
            "",
            f"← {previous} · {branch_label(current, True)} · {following} →",
            "",
            f"Base: `{current['parent']}`",
            "",
            "| # | Change | Base |",
            "|--:|--------|------|",
            *rows,
            "",
            "Review from the bottom of the stack upward. Each change should be reviewed",
            "as an independent unit; use the full stack only for dependency context.",
        ]
    )


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"no stack manifest at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError(f"stack manifest at {path} must contain an object")
    return data


def save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def status_payload(data: dict[str, Any], repo: Path) -> dict[str, Any]:
    rows, errors = inspect_repo(data, repo)
    return {
        "version": data.get("version"),
        "provider": data.get("provider", "github"),
        "trunk": data.get("trunk"),
        "remote": data.get("remote"),
        "valid": not errors,
        "branches": rows,
        "errors": errors,
    }


def print_status(payload: dict[str, Any]) -> None:
    print(
        f"Forge stack: {payload['trunk']} via {payload['remote']} "
        f"({payload['provider']})"
    )
    if not payload["branches"]:
        print("  (no stacked branches)")
    for index, row in enumerate(payload["branches"], start=1):
        pr = f"PR #{row['pr']}" if row.get("pr") else "draft"
        relation = "ok" if row["parent_is_ancestor"] else "broken"
        print(
            f"  {index}. {row['name']} <- {row['parent']}  "
            f"{row['commits']} commits, {row['files']} files, {pr}, {relation}"
        )
    for error in payload["errors"]:
        print(f"  ERROR: {error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and plan stacked GitHub pull requests"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create an empty stack manifest")
    init.add_argument("--trunk", default="main")
    init.add_argument("--remote", default="origin")
    init.add_argument("--provider", choices=sorted(PROVIDERS), default="github")
    init.add_argument("--force", action="store_true")

    add = sub.add_parser("add", help="add a branch to the stack")
    add.add_argument("branch")
    add.add_argument("--parent", required=True)
    add.add_argument("--pr", type=int)

    link = sub.add_parser("link", help="associate an existing PR number with a branch")
    link.add_argument("branch")
    link.add_argument("pr", type=int)

    status = sub.add_parser("status", help="show stack and git health")
    status.add_argument("--json", action="store_true")

    sub.add_parser("check", help="validate manifest and git ancestry")

    plan = sub.add_parser("plan", help="print commands without executing them")
    plan.add_argument("action", choices=("submit", "restack", "land"))
    plan.add_argument("--tool", choices=sorted(PROVIDERS))

    body = sub.add_parser("body", help="render stack navigation for one PR")
    body.add_argument("branch")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    path = args.manifest if args.manifest.is_absolute() else repo / args.manifest

    try:
        if args.command == "init":
            if path.exists() and not args.force:
                raise ValueError(f"{path} already exists; pass --force to replace it")
            data = {
                "version": MANIFEST_VERSION,
                "provider": args.provider,
                "trunk": args.trunk,
                "remote": args.remote,
                "branches": [],
            }
            errors = validate_manifest(data)
            if errors:
                raise ValueError("; ".join(errors))
            save_manifest(path, data)
            print(f"Created {path}")
            return 0

        data = load_manifest(path)
        manifest_errors = validate_manifest(data)
        if manifest_errors and args.command not in {"status", "check"}:
            raise ValueError("; ".join(manifest_errors))

        if args.command == "add":
            candidate = {"name": args.branch, "parent": args.parent}
            if args.pr is not None:
                candidate["pr"] = args.pr
            data["branches"].append(candidate)
            errors = validate_manifest(data)
            if errors:
                raise ValueError("; ".join(errors))
            save_manifest(path, data)
            print(f"Added {args.branch} on {args.parent}")
            return 0

        if args.command == "link":
            for branch in data["branches"]:
                if branch["name"] == args.branch:
                    branch["pr"] = args.pr
                    save_manifest(path, data)
                    print(f"Linked {args.branch} to PR #{args.pr}")
                    return 0
            raise ValueError(f"branch {args.branch!r} is not in the stack")

        if args.command in {"status", "check"}:
            payload = status_payload(data, repo)
            if args.command == "status" and args.json:
                print(json.dumps(payload, indent=2))
            else:
                print_status(payload)
            return 0 if payload["valid"] else 1

        if args.command == "plan":
            print("# Plan only: inspect these commands before running them.")
            tool = args.tool or data.get("provider", "github")
            for command in adapter_plan(data, args.action, tool):
                print(command)
            return 0

        if args.command == "body":
            print(pr_body(data, args.branch))
            return 0
    except (TypeError, ValueError) as exc:
        print(f"forge-stack: {exc}", file=sys.stderr)
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
