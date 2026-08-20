# Constellation Integration

Forge provides a small, provider-neutral routing bundle for work that spans a private
multi-repository constellation. This document defines the evidence contract for that
bundle; it is not a claim that Forge understands every domain repository or that a
repository is secure because a profile matched it.

## Scope

The `constellation-integration` bundle combines planning, task-ledger coordination,
defensive review, release qualification, and incident-quality documentation. The doctor
profile recognizes workspace and repository aliases and reports a tracked-file language
matrix. It does not certify a repository, grant security tooling, mutate GitHub, deploy
software, or authorize production changes.

Capability claims require evidence from the implementation, tests, generated release
surface, or an actual CI run. A README or this document can state a contract, but it
cannot prove that the contract is implemented.

## Cross-repository planning

Use one task ledger row per deliverable. Every row records an explicit `depends_on` list,
an owner, acceptance criteria, and the exact verification command. A synchronization pass
must stop on a conflict, preserve both local and remote evidence, and plan again after a
human resolves the disagreement. It must never silently overwrite a remote issue, task,
or repository file.

Recommended order:

1. Establish the workspace and repository alias from the doctor profile.
2. Read the target repository instructions, issue, and relevant contract files.
3. Record dependencies and acceptance criteria in the ledger before implementation.
4. Run cross-repository checks as read-only comparisons.
5. Review the threat model and release evidence before proposing an external effect.

## Security and secrets

The integration is defensive-only. It may identify missing controls and document
remediation, but it does not build offensive tooling or treat a profile match as an
authorization signal. Never log secrets, credentials, prompts, raw tool arguments, or
repository content that is not needed for the evidence. Receipts and CI artifacts must
be privacy-safe and contain references or digests rather than secret values. Do not paste
the token into an issue, task, receipt, prompt, or release artifact.

## Release qualification

Release evidence names the source commit, the exact CI run, the commands executed, and
the actual pass/fail result. A local test result is useful but is not CI evidence; an
expected workflow is not an actual run. Before claiming readiness, inspect the full diff,
run `git diff --check`, remove generated output, and record the CI run URL or run id when
one exists. Do not assume the checks passed because a job was requested.

## Incident-quality documentation

Incident notes stay blameless and evidence-led: impact, timeline, detection, mitigation,
root cause, contributing factors, and follow-up owners. Record uncertainty explicitly and
separate observed facts from hypotheses. External actions remain behind the host policy,
approval, and receipt boundaries; this bundle never supplies those permissions.
