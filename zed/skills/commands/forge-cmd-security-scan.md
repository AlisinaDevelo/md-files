---
name: forge-cmd-security-scan
description: Defensive security review of the current diff or a target path
disable-model-invocation: true
---

Perform a defensive security review of the current changes or the path the user specified.

Use any text the user typed after the command as a target path or scope hint.

Start by running `git status --short` and `git diff HEAD` to see the current changes. If the user gave a specific path, read those files directly.

Trace untrusted input to every sink. Check, anchored to OWASP/CWE:

- Injection (SQL/NoSQL/command/template/header), XSS, SSRF, path traversal, XXE.
- AuthN/AuthZ: missing or broken access control, IDOR, privilege escalation, token validation.
- Secrets: hardcoded keys/passwords/tokens, secrets in logs or errors.
- Crypto: weak algorithms, predictable randomness for security, password storage.
- Input validation, mass assignment, unsafe deserialization.
- Security headers, CORS, cookie flags, sensitive-data exposure.

Report findings by severity (CRITICAL/HIGH/MEDIUM/LOW) with:

- Location (`file:line`)
- Why it's exploitable
- A concrete attack scenario
- Remediation with a safe code pattern

Severity = exploitability x impact; don't inflate. Label anything you can't confirm reachable as needs-verification. Defensive analysis only.
