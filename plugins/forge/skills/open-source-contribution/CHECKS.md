# Exact-Head Contribution Checks

Create a reviewed JSON profile outside the source tree, or commit it as source:

```json
{
  "schema": 1,
  "base_ref": "origin/main",
  "instruction_paths": ["AGENTS.md", "CONTRIBUTING.md"],
  "checks": [
    {
      "id": "tests",
      "argv": ["python3", "-m", "pytest", "tests/", "-q"],
      "timeout_seconds": 300,
      "max_output_bytes": 1048576
    }
  ]
}
```

Use only instruction paths that actually exist. Choose a base that is an ancestor of
the tested commit. Pin toolchains separately; the helper does not install dependencies.
Commands are explicit argument vectors, never implicitly interpreted by a shell. A
shell, network client or destructive tool in the vector still has its normal authority.
Do not put secrets in the profile or commands. The plan displays the reviewed vectors.

```bash
python3 scripts/forge-contribute.py plan --repo /path/to/upstream --profile /path/to/checks.json
python3 scripts/forge-contribute.py run --repo /path/to/upstream --profile /path/to/checks.json \
  --yes --output /path/outside/upstream/receipt.json
python3 scripts/forge-contribute.py verify --repo /path/to/upstream --profile /path/to/checks.json \
  --receipt /path/outside/upstream/receipt.json
```

In an installed skill, the helper is `scripts/forge-contribute.py` relative to this
directory. It is self-contained, requires Python 3.9+ and Git, and uses POSIX process
groups for execution cleanup. Planning and verification do not execute check vectors.

## Contract

- Source must be clean, including untracked files. Ignored build output is not source
  evidence and must be cleaned separately after testing.
- Checks execute sequentially, stopping on the first failure. Timeout, excessive output,
  spawn failure, nonzero exit or changed source/contracts cannot produce acceptance.
- Output is bounded and hashed in memory, not retained or printed. Receipts contain IDs,
  command/output digests and outcomes, not raw output, arguments, environment or paths.
- Receipts must be new files outside the repository. Existing files are never replaced.
- Verification requires every declared check to pass and the current source/contract
  to match the receipt. This verifies consistency, not authenticity: anyone able to
  fabricate the JSON can fabricate evidence. Use trusted execution and signed release
  provenance when an adversarial trust boundary requires it.
- Pre/post source checks do not detect a mutation that is completely restored before
  the final check. Escaped processes, external effects and ignored data are outside the
  contract. Tests remain responsible for covering the actual issue acceptance criteria.
