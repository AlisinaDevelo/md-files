---
name: forge-cmd-changelog
description: Draft a changelog entry from commits since the last release
disable-model-invocation: true
---

Draft a changelog entry in Keep a Changelog style from the commits since the last release.

Use any text the user typed after the command as a version tag, tag range, or version number for the new entry.

Start by running:

- `git describe --tags --abbrev=0 2>/dev/null || echo "(none)"` to find the last tag
- `git log <last-tag>..HEAD --oneline` (or `git log --oneline -30` if no tag) to get commits since

If the user specified a version tag or range, use that instead.

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

Group commits by their Conventional Commit type (feat → Added, fix → Fixed, etc.). Write for the *reader of the release*, not as a commit dump: describe the user-facing effect, collapse noise (merge commits, formatting, internal refactors that don't affect users), and omit sections with nothing in them. Don't invent changes that aren't in the commits; if a commit's intent is unclear, flag it rather than guessing.
