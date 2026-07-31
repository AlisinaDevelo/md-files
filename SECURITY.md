# Security Policy

## Supported Versions

Security fixes are developed against the latest release on the `main` branch. Older
releases may not receive a backport unless the issue is critical and the fix is small.

## Reporting a Vulnerability

Please do not open a public issue for an undisclosed vulnerability. Use GitHub's private
security advisory flow for this repository:

<https://github.com/AlisinaDevelo/md-files/security/advisories/new>

Include the affected version or commit, the smallest reproducible example, impact,
whether credentials or external systems are involved, and any safe mitigation. Redact
secrets and personal data from reports and reproduction artifacts.

If the private advisory flow is unavailable, open a minimal issue asking for a private
contact channel without including exploit details.

## Response Expectations

We will acknowledge a report when practical, reproduce it, classify its impact, and
coordinate disclosure timing with the reporter. Do not test against systems or
repositories you do not own or have explicit permission to assess.

Forge is a toolkit of Markdown, configuration, hooks, and scripts. A report may affect
the toolkit itself, an installation path, a host integration, or an example configuration;
please identify which boundary is involved.

## Security Boundaries

Forge does not replace operating-system isolation, host permissions, GitHub repository
rules, or credential management. Mutating workflows must still use least-privilege tokens,
explicit approvals, and protected branches.
