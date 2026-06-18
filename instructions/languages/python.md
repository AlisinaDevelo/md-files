# Python Instructions

Paste the relevant lines into a project `CLAUDE.md`. Keep only what's true for the repo.

## Style & types

- Follow PEP 8; let the formatter (ruff/black) own layout — don't hand-format.
- Type-annotate public functions and non-trivial code. Run the type checker (mypy/
  pyright) if the project uses one; keep it clean.
- Prefer explicit over clever. Readability counts.

## Idioms

- Use comprehensions and generators for clarity, not to cram logic onto one line.
- Context managers (`with`) for resources — files, locks, connections, sessions.
- `pathlib` over `os.path`; f-strings over `%`/`.format`.
- Dataclasses / pydantic models for structured data instead of bare dicts/tuples.
- EAFP where idiomatic, but don't swallow exceptions you don't understand.

## Errors

- Raise specific exceptions; never bare `except:`. Catch the narrowest type.
- Don't use exceptions for normal control flow across boundaries.
- Validate inputs at the edge (pydantic) and trust them inside.

## Dependencies & env

- Use the project's tooling (uv/poetry/pip-tools) and a virtual env. Pin in the lockfile.
- Don't add a dependency for something the stdlib does well.

## Testing

- Match the project's framework (pytest typical). Use fixtures over setup boilerplate.
- Parametrize edge cases. Mock at real boundaries only.
- Run the suite + lint + type-check before declaring done.
