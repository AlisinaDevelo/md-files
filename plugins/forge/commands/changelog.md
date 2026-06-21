---
description: Draft a changelog entry from the commits since the last release
argument-hint: "[optional: a version tag/range, defaults to since the last tag]"
allowed-tools: Read, Bash(git log:*), Bash(git tag:*), Bash(git describe:*)
model: sonnet
---

Draft a changelog entry in Keep a Changelog style from the commits since the last release.

- Last tag: !`git describe --tags --abbrev=0 2>/dev/null || echo "(none)"`
- Commits since last tag: !`git log $(git describe --tags --abbrev=0 2>/dev/null)..HEAD --oneline 2>/dev/null || git log --oneline -30`

Range/version (if provided): $ARGUMENTS

Produce an entry:

```text
## [<version>] — <date>

### Added
- <user-facing new capabilities>

### Changed
- <behavior changes>

### Fixed
- <bug fixes>

### Removed / Deprecated
- <as applicable>
```

Group the commits by their Conventional Commit type (feat → Added, fix → Fixed, etc.).
Write for the *reader of the release*, not as a commit dump: describe the user-facing effect,
collapse noise (merge commits, formatting, internal refactors that don't affect users), and
omit sections with nothing in them. Don't invent changes that aren't in the commits; if a
commit's intent is unclear, flag it rather than guessing.
