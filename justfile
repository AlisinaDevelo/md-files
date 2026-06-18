# Forge toolkit — task runner.
# Install just: https://just.systems  ·  run `just` to list recipes.

# Show available recipes
default:
    @just --list

# Validate structure: frontmatter, JSON, hook scripts, marketplace sources
validate:
    ./scripts/validate.sh

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

# Lint python hook scripts (requires ruff)
lint-py:
    ruff check plugins/forge/hooks/scripts tests evals

# Run every check that CI runs
check: validate test lint-md
    @echo "✅ all local checks passed"

# Score the prompt evals (deterministic structural checks; no API key needed)
eval:
    python3 evals/run.py

# Score the prompt evals with an LLM judge (requires ANTHROPIC_API_KEY)
eval-llm:
    python3 evals/run.py --judge

# Symlink agents/skills/commands into ~/.claude (dry run)
install-dry:
    ./scripts/install.sh --dry-run
