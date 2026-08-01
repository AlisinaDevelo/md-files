---
description: Run the read-only Forge capability and merge-readiness preflight
argument-hint: "[--json|--offline|--strict]"
---

Run `python3 scripts/forge-doctor.py` from the repository root with the requested flags.
Use the `doctor` skill for interpretation.

Report the overall status and the checks that are `warn`, `fail`, or `unknown`. Do not
repair findings automatically. For JSON consumers, preserve the schema-versioned report
exactly and explain any skipped network checks.
