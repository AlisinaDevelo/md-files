#!/usr/bin/env bash
# Run the release, install, replay, and quality gates without hosted CI.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON:-python3}"
EVIDENCE_OUTPUT="${FORGE_LOCAL_RELEASE_EVIDENCE:-${TMPDIR:-/tmp}/forge-local-release-evidence.json}"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/forge-local-release.XXXXXX")"

cleanup() {
  if [ -d "$TMP_ROOT" ]; then
    rm -rf "$TMP_ROOT"
  fi
}

trap cleanup EXIT

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'local-release-check: required command is unavailable: %s\n' "$1" >&2
    exit 1
  }
}

run_logged() {
  local label="$1"
  local log="$2"
  shift 2
  printf '[%s]\n' "$label"
  if "$@" >"$log" 2>&1; then
    tail -n 6 "$log"
  else
    cat "$log" >&2
    return 1
  fi
}

for command in "$PYTHON_BIN" jq npx claude codex shellcheck; do
  require_command "$command"
done

if [ -n "$(git status --porcelain)" ]; then
  printf 'local-release-check: source tree must be clean before packaging\n' >&2
  exit 1
fi
git diff --check

version="$(jq -r '.version' plugins/forge/.claude-plugin/plugin.json)"
commit="$(git rev-parse HEAD)"
epoch="$(git show -s --format=%ct HEAD)"
printf 'Forge local release gate: version=%s commit=%s\n' "$version" "$commit"

printf '[Forge Doctor]\n'
"$PYTHON_BIN" scripts/forge-doctor.py --strict --json >"$TMP_ROOT/doctor.json"
jq -e '.overall == "pass" and .summary.fail == 0 and .summary.warn == 0 and .summary.unknown == 0' \
  "$TMP_ROOT/doctor.json" >/dev/null
printf 'doctor=pass\n'

run_logged "Structure validation" "$TMP_ROOT/validate.log" ./scripts/validate.sh
run_logged "Full pytest suite" "$TMP_ROOT/pytest.log" "$PYTHON_BIN" -m pytest tests/ -q -ra
run_logged "Static evals" "$TMP_ROOT/evals.log" "$PYTHON_BIN" evals/run.py
grep -Eq 'Static eval: .*0 failures' "$TMP_ROOT/evals.log"

run_logged "Trajectory security corpus" "$TMP_ROOT/trajectory.log" \
  "$PYTHON_BIN" scripts/forge-trajectory-evals.py evaluate \
  --corpus tests/fixtures/trajectories/v1.jsonl --json
jq -e '.status == "passed" and .case_count == 4 and .threat_cases == 2 and .judge.release_oracle == "deterministic" and .metrics.replay_stability == 1' \
  "$TMP_ROOT/trajectory.log" >/dev/null
printf 'trajectory-evals=passed cases=4 threat_cases=2\n'

run_logged "Authority contract corpus" "$TMP_ROOT/authority.log" \
  "$PYTHON_BIN" scripts/forge-authority.py evaluate \
  --corpus tests/fixtures/authority/v1.jsonl --json
jq -e '.status == "passed" and .case_count == 11 and .threat_cases == 5 and .deterministic == true and .authentication_boundary == "external-reference"' \
  "$TMP_ROOT/authority.log" >/dev/null
printf 'authority-contract=passed cases=11 threat_cases=5\n'

run_logged "Host admission corpus" "$TMP_ROOT/host-admission.log" \
  "$PYTHON_BIN" scripts/forge-host-admission.py evaluate \
  --corpus tests/fixtures/host-admission/v1.jsonl --json
jq -e '.status == "passed" and .case_count == 2 and .threat_cases == 1 and .deterministic == true and .authentication_boundary == "external-reference"' \
  "$TMP_ROOT/host-admission.log" >/dev/null
printf 'host-admission=passed cases=2 threat_cases=1\n'

run_logged "A2A Agent Card corpus" "$TMP_ROOT/a2a-card.log" \
  "$PYTHON_BIN" scripts/forge-a2a-card.py evaluate \
  --corpus tests/fixtures/a2a-card/v1.jsonl --json
jq -e '.status == "passed" and .case_count == 4 and .threat_cases == 3 and .deterministic == true' \
  "$TMP_ROOT/a2a-card.log" >/dev/null
printf 'a2a-card=passed cases=4 threat_cases=3\n'

run_logged "A2A task handoff corpus" "$TMP_ROOT/a2a-task.log" \
  "$PYTHON_BIN" scripts/forge-a2a-task.py evaluate \
  --corpus tests/fixtures/a2a-task/v1.jsonl --json
jq -e '.status == "passed" and .case_count == 8 and .threat_cases == 5 and .deterministic == true' \
  "$TMP_ROOT/a2a-task.log" >/dev/null
printf 'a2a-task=passed cases=8 threat_cases=5\n'

run_logged "Cross-host scenarios" "$TMP_ROOT/scenarios.log" \
  "$PYTHON_BIN" evals/run_scenarios.py --adapter all --no-receipts --output "$TMP_ROOT/scenarios.json"
jq -e '.summary.failed == 0 and .summary.flaky == 0 and .summary.passed > 0' \
  "$TMP_ROOT/scenarios.json" >/dev/null

"$PYTHON_BIN" plugins/forge/skills/orchestration/scripts/forge-backends.py \
  conformance --backend all >"$TMP_ROOT/backends.json"
jq -e '.status == "passed"' "$TMP_ROOT/backends.json" >/dev/null
printf 'backend-conformance=passed\n'

run_logged "Deterministic chaos corpus" "$TMP_ROOT/chaos.log" \
  "$PYTHON_BIN" plugins/forge/skills/orchestration/scripts/forge-chaos.py corpus \
  --output "$TMP_ROOT/chaos.json"
jq -e '.status == "passed" and (.seeds | length) > 0' "$TMP_ROOT/chaos.json" >/dev/null

PYTHON_COMPILE_TARGETS=(
  plugins/forge/hooks/scripts/*.py
  plugins/forge/skills/*/scripts/*.py
  scripts/*.py
  evals/*.py
  tests/*.py
)
run_logged "Python compilation" "$TMP_ROOT/compile.log" "$PYTHON_BIN" -m py_compile "${PYTHON_COMPILE_TARGETS[@]}"

PYTHON_LINT_TARGETS=(
  plugins/forge/hooks/scripts
  plugins/forge/skills/policy/scripts
  plugins/forge/skills/stacked-changes/scripts
  plugins/forge/skills/doctor/scripts
  plugins/forge/skills/observability/scripts
  plugins/forge/skills/task-ledger/scripts
  plugins/forge/skills/orchestration/scripts
  scripts/build_release.py
  scripts/forge-attestation.py
  scripts/forge-trajectory-evals.py
  scripts/forge-authority.py
  scripts/forge-host-admission.py
  scripts/forge-a2a-card.py
  scripts/forge-a2a-task.py
  scripts/build_openai_submission_evidence.py
  scripts/compile_capabilities.py
  scripts/render_capabilities.py
  scripts/diff_capabilities.py
  scripts/migrate_capabilities.py
  scripts/validate_codex_plugin.py
  scripts/verify_release.py
  scripts/generate_catalog.py
  scripts/forge-doctor.py
  scripts/forge-policy.py
  scripts/forge-receipts.py
  scripts/forge-runtime.py
  scripts/forge-lineage.py
  scripts/forge-provenance.py
  scripts/forge-gh-aw.py
  scripts/forge-gh-aw-provider.py
  scripts/forge-tasks.py
  scripts/forge-stack-sync.py
  evals
  tests
)
run_logged "Ruff" "$TMP_ROOT/ruff.log" "$PYTHON_BIN" -m ruff check "${PYTHON_LINT_TARGETS[@]}"

export NPM_CONFIG_CACHE="$TMP_ROOT/npm-cache"
run_logged "Markdown lint" "$TMP_ROOT/markdownlint.log" \
  npx --yes markdownlint-cli2@0.23.2 "**/*.md"

skills_log="$TMP_ROOT/skills-ref.log"
: >"$skills_log"
skill_count=0
while IFS= read -r -d '' skill; do
  if ! npx --yes skills-ref@0.1.5 validate "$skill" >>"$skills_log" 2>&1; then
    cat "$skills_log" >&2
    exit 1
  fi
  skill_count=$((skill_count + 1))
done < <(find plugins/forge/skills -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
printf 'skills-ref=passed skills=%s\n' "$skill_count"

run_logged "Claude plugin validation" "$TMP_ROOT/claude-validate.log" \
  claude plugin validate --strict plugins/forge
run_logged "ShellCheck" "$TMP_ROOT/shellcheck.log" \
  shellcheck plugins/forge/hooks/scripts/*.sh scripts/*.sh

mkdir "$TMP_ROOT/release-first" "$TMP_ROOT/release-second"
run_logged "Release build 1" "$TMP_ROOT/build-first.log" \
  "$PYTHON_BIN" scripts/build_release.py --output "$TMP_ROOT/release-first" \
  --version "$version" --source-date-epoch "$epoch"
run_logged "Release build 2" "$TMP_ROOT/build-second.log" \
  "$PYTHON_BIN" scripts/build_release.py --output "$TMP_ROOT/release-second" \
  --version "$version" --source-date-epoch "$epoch"

artifact_count="$(find "$TMP_ROOT/release-first" -maxdepth 1 -type f | wc -l | tr -d ' ')"
second_count="$(find "$TMP_ROOT/release-second" -maxdepth 1 -type f | wc -l | tr -d ' ')"
test "$artifact_count" = "$second_count"
for artifact in "$TMP_ROOT/release-first"/*; do
  name="$(basename "$artifact")"
  cmp "$artifact" "$TMP_ROOT/release-second/$name"
done
printf 'byte-identical-artifacts=%s\n' "$artifact_count"

for release_dir in "$TMP_ROOT/release-first" "$TMP_ROOT/release-second"; do
  run_logged "Offline release verification: $(basename "$release_dir")" \
    "$TMP_ROOT/$(basename "$release_dir")-verify.log" \
    "$PYTHON_BIN" scripts/verify_release.py \
    --manifest "$release_dir/forge-$version-manifest.json" \
    --root "$release_dir" --version "$version" --commit "$commit"
  run_logged "Codex archive validation: $(basename "$release_dir")" \
    "$TMP_ROOT/$(basename "$release_dir")-codex.log" \
    "$PYTHON_BIN" scripts/validate_codex_plugin.py \
    --archive "$release_dir/forge-$version-codex.tar.gz" --version "$version"
done
run_logged "Codex marketplace validation" "$TMP_ROOT/codex-marketplace.log" \
  "$PYTHON_BIN" scripts/validate_codex_plugin.py --marketplace .agents/plugins/marketplace.json --root .

run_logged "Release attestation verification" "$TMP_ROOT/attestation.log" \
  "$PYTHON_BIN" scripts/forge-attestation.py self-test \
  --manifest "$TMP_ROOT/release-first/forge-$version-manifest.json" \
  --root "$TMP_ROOT/release-first" \
  --policy policies/release.json \
  --source-ref "refs/tags/v$version" \
  --json
jq -e '.status == "passed" and (.profiles | length) == 2 and (.negative_cases | length) == 6 and all(.profiles[]; .status == "verified") and all(.negative_cases[]; .status == "pass")' \
  "$TMP_ROOT/attestation.log" >/dev/null
printf 'release-attestation=passed profiles=2 negative_cases=6\n'

run_logged "Installed candidate evidence and replay" "$TMP_ROOT/submission.log" \
  "$PYTHON_BIN" scripts/build_openai_submission_evidence.py --output "$EVIDENCE_OUTPUT"
run_logged "Claude/Codex marketplace lifecycle" "$TMP_ROOT/marketplace-smoke.log" \
  ./scripts/marketplace-smoke.sh "$ROOT"

jq -e --arg commit "$commit" \
  '.candidate.source_commit == $commit and .candidate.installation.archive_bytes_match == true and .candidate.installation.strict_validation == "pass" and .candidate.replay.status == "pass" and .candidate.replay.identical == true and ([.cases[] | select(.status != "pass")] | length) == 0' \
  "$EVIDENCE_OUTPUT" >/dev/null
jq '{source_commit: .candidate.source_commit, archive_sha256: .candidate.archive_sha256, installed_files: .candidate.installation.installed_files, installed_skills: .candidate.installation.installed_skills, replay: .candidate.replay, case_count: (.cases | length)}' "$EVIDENCE_OUTPUT"
printf 'LOCAL_RELEASE_GATE=passed\nEvidence: %s\n' "$EVIDENCE_OUTPUT"
