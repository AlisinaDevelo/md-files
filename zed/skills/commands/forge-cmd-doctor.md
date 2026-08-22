---
name: forge-cmd-doctor
description: Run the read-only Forge capability and merge-readiness preflight
disable-model-invocation: true
---

Run the read-only Forge doctor script with the requested flags. For a global Agent Skills
install, use `python3 ~/.agents/skills/doctor/scripts/forge-doctor.py`; from a Forge
checkout, use `python3 plugins/forge/skills/doctor/scripts/forge-doctor.py`. Do not assume
that the target repository contains a Forge `scripts/` directory.

Use the `doctor` skill for interpretation.

Report the overall status and the checks that are `warn`, `fail`, or `unknown`. Do not
repair findings automatically. For JSON consumers, preserve the schema-versioned report
exactly and explain any skipped network checks.
