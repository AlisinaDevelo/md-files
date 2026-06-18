#!/usr/bin/env python3
"""PreToolUse(Write|Edit) secret scanner — block writing likely credentials.

Reads the hook payload from stdin and inspects the content about to be written
or the replacement text of an edit. If it matches a high-confidence secret
pattern, exit 2 to block and explain on stderr. Otherwise exit 0.

Fails OPEN on parse errors. High-precision patterns only — the cost of a false
positive (blocking a legitimate edit) is high, so placeholders like
"your-api-key-here", "xxxx", and obvious examples are tolerated.
"""
import json
import re
import sys

PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}", "AWS secret key"),
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", "private key"),
    (r"gh[pousr]_[A-Za-z0-9]{36,}", "GitHub token"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"sk-[A-Za-z0-9]{32,}", "OpenAI-style secret key"),
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key"),
    (r"AIza[0-9A-Za-z_-]{35}", "Google API key"),
    (r"(?i)(secret|password|passwd|token|api[_-]?key)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]",
     "hardcoded credential assignment"),
]

# Strings that signal an obvious placeholder; if present near a match we relax.
PLACEHOLDER = re.compile(
    r"(?i)(your|example|placeholder|dummy|fake|test|sample|changeme|xxxx|<.*>|\.\.\.)",
)

COMPILED = [(re.compile(p), why) for p, why in PATTERNS]


def extract_text(payload: dict) -> str:
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    if tool == "Write":
        return ti.get("content", "") or ""
    if tool == "Edit":
        return ti.get("new_string", "") or ""
    if tool == "MultiEdit":
        return "\n".join(e.get("new_string", "") for e in ti.get("edits", []) or [])
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    text = extract_text(payload)
    if not text:
        return 0

    for pattern, why in COMPILED:
        m = pattern.search(text)
        if not m:
            continue
        # Tolerate obvious placeholders on the same line.
        line = text[text.rfind("\n", 0, m.start()) + 1 : text.find("\n", m.end())]
        if PLACEHOLDER.search(line):
            continue
        sys.stderr.write(
            f"⛔ Blocked by Forge secret scanner: looks like a {why}.\n"
            "   Don't commit secrets to source. Use an env var, a secrets manager,\n"
            "   or a .env file that's gitignored. If this is a false positive (e.g.\n"
            "   a fixture), make it an obvious placeholder or load it from config.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
