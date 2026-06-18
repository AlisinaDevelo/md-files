# CI & Headless Usage

Forge isn't only for interactive sessions. The same agents, skills, and commands work in
**headless mode** (`claude -p`), which lets you run them non-interactively in CI — for
example, an automated review on every pull request.

## Headless basics

`claude -p "<prompt>"` (print mode) runs a single non-interactive turn and writes the
result to stdout. It picks up your installed plugins, so Forge's commands and agents are
available. Useful flags:

- `-p/--print` — non-interactive; print and exit.
- `--output-format json` — structured result (parse it in scripts) instead of plain text.
- `--permission-mode` — control whether tools can run unattended (see the permissions
  docs). In CI you typically want a tightly scoped allowlist, not broad write access.
- `--model` — pin the model for reproducible runs.

```bash
# Review the changes on this branch vs main, headless:
git diff main...HEAD | claude -p "Use the code-review rubric to review this diff. \
  Report blocking issues only, as a short list." --output-format json
```

## Pattern: automated PR review

The shape of a CI review job, framework-agnostic:

1. Check out the PR with enough history to diff against the base branch.
2. Install Claude Code and the Forge plugin.
3. Pipe the diff into `claude -p` with a review prompt (lean on the `code-review-rubric`
   skill or the `/review` command's intent).
4. Capture the output and post it as a PR comment, or fail the job on blocking findings.

```yaml
# .github/workflows/ai-review.yml  (template — adapt to your setup)
name: AI review
on: pull_request
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # need history to diff against the base
      - name: Install Claude Code
        run: npm install -g @anthropic-ai/claude-code
      - name: Add Forge
        run: |
          claude plugin marketplace add AlisinaDevelo/md-files
          claude plugin install forge@forge
      - name: Review the diff
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          git diff origin/${{ github.base_ref }}...HEAD > /tmp/pr.diff
          claude -p "Review the diff in /tmp/pr.diff using the code-review rubric. \
            Output a markdown list of blocking issues with file:line, or 'No blocking issues.'" \
            --output-format text > /tmp/review.md
          cat /tmp/review.md
```

> Anthropic also ships an official GitHub Action for Claude Code. If you prefer a
> maintained action over raw CLI steps, check the current Claude Code docs for its name
> and inputs rather than copying a version from memory — action APIs change.

## Guardrails in CI

The Forge hooks run in headless mode too. In an unattended pipeline that means:

- **`guard-bash`** still blocks catastrophic commands — valuable when the agent has shell
  access on a runner.
- **`scan-secrets`** still blocks writing credentials into files.
- **`format-file`** / **`notify`** are best-effort and harmless in CI (no formatter or
  notifier installed → silent no-op).

Keep CI permissions tight regardless: an allowlist of the read-only and test commands the
job actually needs, and no broad write/network access. The hooks are a safety net, not a
substitute for least-privilege.

## Reproducibility

Pin the model (`--model claude-sonnet-4-6` or similar) and the plugin version so a review
today and a review next month behave the same way. Treat the prompt as code — review
changes to it like any other.
