---
description: Scaffold a new module/component matching the repo's existing conventions
argument-hint: "<what to scaffold, e.g. 'a new API endpoint for orders' or 'a React Button component'>"
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
model: sonnet
---

Scaffold: $ARGUMENTS

Match the repo's existing conventions — don't impose a generic template.

1. **Find the nearest existing example** of the same kind of thing (an analogous endpoint,
   component, module, or test) with Grep/Glob, and read it. The repo's own pattern is the
   spec: directory layout, naming, imports, framework idioms, how tests are co-located.
2. **Confirm dependencies exist** before using them — check the manifest/neighbors; never
   introduce a new library to scaffold something.
3. **Create the minimal working skeleton** following that pattern: the file(s) in the right
   place, wired up (registered/exported/routed as the convention requires), with a matching
   test stub. No speculative abstraction or features beyond what was asked.
4. **Verify it's wired correctly** — run the build/type-check/test if quick, or show the
   exact command to confirm it compiles and the test is discovered.

Report the files created, how they hook into the existing structure, and the command to run
to see them work. If the repo has no clear precedent for this kind of thing, say so and
propose a structure rather than guessing silently.
