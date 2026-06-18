---
description: Defensive security review of the current diff or a target path
argument-hint: "[optional: path; defaults to current changes]"
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*)
model: sonnet
---

Perform a defensive security review. Target: $ARGUMENTS (if empty, review the current
changes below).

- Status: !`git status --short`
- Diff: !`git diff HEAD`

Trace untrusted input to every sink. Check, anchored to OWASP/CWE:

- Injection (SQL/NoSQL/command/template/header), XSS, SSRF, path traversal, XXE.
- AuthN/AuthZ: missing or broken access control, IDOR, privilege escalation, token
  validation.
- Secrets: hardcoded keys/passwords/tokens, secrets in logs or errors.
- Crypto: weak algorithms, predictable randomness for security, password storage.
- Input validation, mass assignment, unsafe deserialization.
- Security headers, CORS, cookie flags, sensitive-data exposure.

Report findings by severity (CRITICAL/HIGH/MEDIUM/LOW) with location, why it's
exploitable, a concrete attack scenario, and the remediation with a safe code pattern.
Severity = exploitability × impact; don't inflate. Label anything you can't confirm
reachable as needs-verification. Defensive analysis only.
