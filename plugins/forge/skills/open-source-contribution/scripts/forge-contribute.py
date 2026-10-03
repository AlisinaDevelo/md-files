#!/usr/bin/env python3
"""Run reviewed contribution checks and verify digest-only exact-head evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import sys
import time


LIMIT = 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    with Path(path).open("rb") as handle:
        data = handle.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("JSON exceeds 1 MiB")
    return json.loads(data)


def check_environment():
    return dict({key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
                GIT_OPTIONAL_LOCKS="0")


def git(repo, *args):
    env = dict(check_environment(), GIT_LITERAL_PATHSPECS="1", GIT_NO_REPLACE_OBJECTS="1")
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                            capture_output=True, text=True, env=env, timeout=15)
    if result.returncode:
        raise ValueError("Git revision or repository check failed")
    return result.stdout.strip()


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def contract(path):
    value = read_json(path)
    if not isinstance(value, dict) or set(value) != {"schema", "base_ref", "instruction_paths", "checks"}:
        raise ValueError("contract requires schema, base_ref, instruction_paths and checks")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("unsupported contract schema")
    if not isinstance(value["base_ref"], str) or not 1 <= len(value["base_ref"]) <= 128:
        raise ValueError("invalid base_ref")
    paths = value["instruction_paths"]
    if not isinstance(paths, list) or len(paths) > 32 or any(not isinstance(p, str) for p in paths):
        raise ValueError("invalid instruction_paths")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate instruction path")
    checks = value["checks"]
    if not isinstance(checks, list) or not 1 <= len(checks) <= 32:
        raise ValueError("declare between 1 and 32 checks")
    ids = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"id", "argv", "timeout_seconds", "max_output_bytes"}:
            raise ValueError("invalid check fields")
        check_id = check["id"]
        if not isinstance(check_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", check_id) or check_id in ids:
            raise ValueError("invalid or duplicate check id")
        ids.add(check_id)
        argv = check["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or any(
            not isinstance(arg, str) or not arg or "\0" in arg or len(arg) > 8192 for arg in argv
        ):
            raise ValueError("invalid command vector")
        timeout = check["timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0.05 <= timeout <= 3600:
            raise ValueError("timeout_seconds must be between 0.05 and 3600")
        size = check["max_output_bytes"]
        if type(size) is not int or not 1 <= size <= 16 * LIMIT:
            raise ValueError("max_output_bytes must be between 1 and 16 MiB")
    return value


def verify_committed_bytes(repo):
    algorithm = git(repo, "rev-parse", "--show-object-format")
    if algorithm not in {"sha1", "sha256"}:
        raise ValueError("unsupported Git object format (Git 2.29+ required)")
    entries = [entry for entry in git(repo, "ls-tree", "-r", "-z", "HEAD").split("\0") if entry]
    if len(entries) > 100000:
        raise ValueError("tracked source exceeds 100000 files")
    deadline = time.monotonic() + 30
    total = 0
    for entry in entries:
        if time.monotonic() > deadline:
            raise ValueError("tracked byte verification exceeded 30 seconds")
        metadata, name = entry.split("\t", 1)
        mode, kind, expected = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("tracked source requires an unsupported Git mode")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("tracked path escapes the repository")
        if any(repo.joinpath(*relative.parts[:end]).is_symlink() for end in range(1, len(relative.parts))):
            raise ValueError("tracked source traverses a directory symlink")
        path = repo / name
        if mode == "120000":
            content = os.fsencode(os.readlink(path))
            hasher = hashlib.new(algorithm, f"blob {len(content)}\0".encode() + content)
            total += len(content)
        else:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("tracked source is not a regular file")
                if bool(before.st_mode & stat.S_IXUSR) != (mode == "100755"):
                    raise ValueError("tracked executable mode differs from HEAD")
                if total + before.st_size > 512 * LIMIT:
                    raise ValueError("tracked source exceeds 512 MiB")
                hasher = hashlib.new(algorithm, f"blob {before.st_size}\0".encode())
                while True:
                    if time.monotonic() > deadline:
                        raise ValueError("tracked byte verification exceeded 30 seconds")
                    chunk = handle.read(LIMIT)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 512 * LIMIT:
                        raise ValueError("tracked source exceeds 512 MiB")
                    hasher.update(chunk)
                after = os.fstat(handle.fileno())
                fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                if any(getattr(before, field) != getattr(after, field) for field in fields):
                    raise ValueError("tracked source changed while being read")
                current = path.lstat()
                if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
                    raise ValueError("tracked source was replaced while being read")
        if hasher.hexdigest() != expected:
            raise ValueError("tracked bytes differ from HEAD; transformed checkouts are unsupported")


def source(repo, profile):
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("--repo must be the Git repository root")
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("source tree must be clean, including untracked files")
    entries = git(repo, "ls-files", "-v", "-z").split("\0")
    if any(entry and (entry[0].islower() or entry[0] == "S") for entry in entries):
        raise ValueError("assume-unchanged and skip-worktree index flags are unsupported")
    if any(entry.startswith("160000 ") for entry in git(repo, "ls-files", "--stage", "-z").split("\0")):
        raise ValueError("submodules require a separate recursive evidence contract")
    verify_committed_bytes(repo)
    commit = git(repo, "rev-parse", "HEAD")
    base = git(repo, "rev-parse", "--verify", "--end-of-options", profile["base_ref"] + "^{commit}")
    git(repo, "merge-base", "--is-ancestor", base, commit)
    instructions = {}
    for name in profile["instruction_paths"]:
        relative = PurePosixPath(name)
        if not name or relative.is_absolute() or ".." in relative.parts or "\0" in name:
            raise ValueError("instruction paths must stay within the repository")
        if any(repo.joinpath(*relative.parts[:end]).is_symlink() for end in range(1, len(relative.parts) + 1)):
            raise ValueError("instruction paths must not contain symlinks")
        path = (repo / name).resolve()
        if not within(path, repo) or not path.is_file():
            raise ValueError("instruction path is absent or escapes the repository")
        git(repo, "ls-files", "--error-unmatch", "--", name)
        with path.open("rb") as handle:
            data = handle.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError("instruction file exceeds 1 MiB")
        instructions[name] = hashlib.sha256(data).hexdigest()
    return {"commit": commit, "tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "base_commit": base, "contract_sha256": digest(profile),
            "instructions_sha256": digest(instructions)}


def stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def execute(repo, check):
    result = {"id": check["id"], "argv_sha256": digest(check["argv"]), "status": "spawn-failed",
              "returncode": None, "output_sha256": hashlib.sha256(b"").hexdigest(), "output_bytes": 0}
    try:
        process = subprocess.Popen(check["argv"], cwd=repo, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                                   env=check_environment())
    except OSError:
        return result
    output = hashlib.sha256()
    start = time.monotonic()
    status = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = check["timeout_seconds"] - (time.monotonic() - start)
                if remaining <= 0:
                    status = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    capacity = check["max_output_bytes"] - result["output_bytes"]
                    output.update(chunk[:capacity])
                    result["output_bytes"] += min(len(chunk), capacity)
                    if len(chunk) > capacity:
                        status = "output-limit"
                        break
                if status:
                    break
            if status is None:
                remaining = max(0, check["timeout_seconds"] - (time.monotonic() - start))
                try:
                    process.wait(timeout=remaining)
                    status = "passed" if process.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    status = "timeout"
    finally:
        stop_group(process)
        process.stdout.close()
    result.update(status=status, returncode=process.returncode, output_sha256=output.hexdigest())
    return result


def run(repo, profile_path, profile, before, output_path):
    if os.name != "posix":
        raise ValueError("run requires POSIX process-group cleanup")
    output_path = Path(output_path).absolute()
    if within(output_path.resolve(), repo):
        raise ValueError("receipt output must be outside the repository")
    # Reserve a new file before executing anything; never replace a user's evidence.
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as handle:
        results = []
        for check in profile["checks"]:
            results.append(execute(repo, check))
            if results[-1]["status"] != "passed":
                break
        try:
            unchanged = source(repo, contract(profile_path)) == before
        except (ValueError, OSError, subprocess.SubprocessError):
            unchanged = False
        passed = unchanged and len(results) == len(profile["checks"]) and all(r["status"] == "passed" for r in results)
        receipt = {"schema": 1, "kind": "forge-contribution", "source": before,
                   "status": "passed" if passed else "failed", "source_unchanged": unchanged, "checks": results}
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return receipt


def verify(receipt, profile, current):
    if not isinstance(receipt, dict) or set(receipt) != {"schema", "kind", "source", "status", "source_unchanged", "checks"}:
        raise ValueError("invalid receipt fields")
    if type(receipt["schema"]) is not int or receipt["schema"] != 1 or receipt["kind"] != "forge-contribution" or receipt["status"] != "passed" or receipt["source_unchanged"] is not True:
        raise ValueError("receipt does not record a successful unchanged run")
    if receipt["source"] != current:
        raise ValueError("receipt is stale for the current source or contract")
    results = receipt["checks"]
    if not isinstance(results, list) or len(results) != len(profile["checks"]):
        raise ValueError("receipt is missing declared checks")
    for result, check in zip(results, profile["checks"]):
        if not isinstance(result, dict) or set(result) != {"id", "argv_sha256", "status", "returncode", "output_sha256", "output_bytes"}:
            raise ValueError("invalid check receipt")
        if result["id"] != check["id"] or result["argv_sha256"] != digest(check["argv"]) or result["status"] != "passed" or type(result["returncode"]) is not int or result["returncode"] != 0:
            raise ValueError("check receipt does not match a successful declared command")
        if type(result["output_bytes"]) is not int or not 0 <= result["output_bytes"] <= check["max_output_bytes"] or not isinstance(result["output_sha256"], str) or not re.fullmatch("[0-9a-f]{64}", result["output_sha256"]):
            raise ValueError("invalid output digest or size")
    return {"status": "verified", "source": current, "check_count": len(results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "run", "verify"])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        profile = contract(args.profile)
        current = source(repo, profile)
        if args.action == "plan":
            result = {"status": "ready", "source": current, "checks": profile["checks"]}
        elif args.action == "run":
            if not args.yes or args.output is None:
                raise ValueError("run requires reviewed commands, --yes and --output")
            result = run(repo, args.profile, profile, current, args.output)
        else:
            if args.receipt is None:
                raise ValueError("verify requires --receipt")
            result = verify(read_json(args.receipt), profile, current)
        print(json.dumps(result, sort_keys=True))
        return 1 if result["status"] == "failed" else 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
