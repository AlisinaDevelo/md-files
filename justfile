# Forge toolkit — task runner.
# Install just: https://just.systems  ·  run `just` to list recipes.

# Show available recipes
default:
    @just --list

# Validate structure: frontmatter, JSON, hook scripts, marketplace sources
validate:
    ./scripts/validate.sh

# Regenerate the Forge component catalog
catalog:
    python3 scripts/generate_catalog.py

# Run the hook test suite (installs pytest if missing)
test:
    @python3 -c "import pytest" 2>/dev/null || pip install --quiet pytest
    python3 -m pytest tests/ -v

# Lint markdown
lint-md:
    npx --yes markdownlint-cli2 "**/*.md"

# Lint shell scripts (requires shellcheck)
lint-sh:
    shellcheck plugins/forge/hooks/scripts/*.sh scripts/*.sh

# Lint Python hook, skill, utility, test, and eval scripts (requires ruff)
lint-py:
    ruff check plugins/forge/hooks/scripts plugins/forge/skills/*/scripts scripts/*.py tests evals

# Compare two capability graph revisions without exposing instruction bodies
diff-capabilities before after:
    python3 scripts/diff_capabilities.py --before {{before}} --after {{after}} --format markdown

# Migrate a reviewed v1 graph against the current source tree
migrate-capabilities input output:
    python3 scripts/migrate_capabilities.py --input {{input}} --output {{output}}

# Run every check that CI runs
check: validate test lint-md conformance
    @echo "✅ all local checks passed"

# Score the prompt evals (deterministic structural checks; no API key needed)
eval:
    python3 evals/run.py

# Score the prompt evals with an LLM judge (requires ANTHROPIC_API_KEY)
eval-llm:
    python3 evals/run.py --judge

# Run shared cross-host scenarios; live host runners are opt-in.
conformance:
    python3 evals/run_scenarios.py --adapter all --no-receipts

# Symlink agents/skills/commands into ~/.claude (dry run)
install-dry:
    ./scripts/install.sh --dry-run
