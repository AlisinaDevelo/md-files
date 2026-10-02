"""Run manifest commands under shell-significant installation paths."""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((REPO / "plugins/forge/hooks/hooks.json").read_text())
COMMANDS = [hook["command"] for entries in MANIFEST["hooks"].values() for entry in entries for hook in entry["hooks"]]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("dirname", ["plugin with spaces", "plugin; $literal 'quoted'"])
def test_manifest_command_preserves_installation_path(tmp_path, command, dirname):
    root = tmp_path / dirname
    script_name = command.split("/hooks/scripts/", 1)[1].rstrip('"')
    target = root / "hooks/scripts" / script_name
    target.parent.mkdir(parents=True)
    target.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n')
    target.chmod(0o755)
    result = subprocess.run(command, shell=True, env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(target)
