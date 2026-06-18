# Status line

[`forge-statusline.sh`](forge-statusline.sh) is a Claude Code
[status line](https://code.claude.com/docs/en/statusline): the bar at the bottom of the
session. It reads the session JSON on stdin and prints one line:

```text
Opus · my-project ⎇ main* · ctx 25% · $0.012
```

— model · working directory · git branch (`*` = uncommitted changes) · context-window
usage · session cost.

## Install

Copy the script somewhere stable and point `settings.json` at it:

```bash
cp statusline/forge-statusline.sh ~/.claude/forge-statusline.sh
chmod +x ~/.claude/forge-statusline.sh
```

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/forge-statusline.sh",
    "padding": 1
  }
}
```

## Test it

It's a plain filter — feed it a mock payload:

```bash
echo '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":25},"cost":{"total_cost_usd":0.0123}}' \
  | ./statusline/forge-statusline.sh
```

## Notes

- Uses `jq` when available and falls back to `python3`, so it works without extra installs.
- Computes git state from the session's `workspace.current_dir`, so it's correct even when
  you're working across multiple directories.
- The status line is not a plugin component (it's a `settings.json` key), which is why it
  lives here rather than under `plugins/forge/`.
