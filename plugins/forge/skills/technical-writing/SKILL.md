---
name: technical-writing
description: >-
  Use when writing developer-facing documentation — READMEs, API references,
  architecture docs, ADRs, runbooks, and docstrings. Covers structure by document
  type, writing for the reader's task, and keeping docs accurate against the code.
---

# Technical Writing

Good docs are accurate, task-oriented, and close to the code. Every claim is verified
against the source — never document aspirational behavior.

## Core principles

- **Write for the reader's task.** Lead with what they need to *do* (install, call,
  deploy, debug), then how it works. Answer "how do I use this?" before "how is it
  built?"
- **Show, don't just tell.** Every concept earns a minimal, runnable example derived from
  real signatures/tests. Verify examples would actually work.
- **Document the contract and the edges.** Inputs, outputs, errors, side effects,
  preconditions, gotchas. Failure modes are often the most useful part.
- **Keep docs near the code** so they stay true. Prefer docstrings and in-repo docs over
  external wikis that drift.
- **Match the project's voice.** Don't impose a new style on a repo that has one.

## By document type

**README** — what it is, why it exists, a quickstart that actually runs, common tasks,
and links out. No wall of prose before the first command. Structure: title → one-line
pitch → install → quickstart → usage → links.

**API reference** — one entry per public symbol: signature, parameters (types +
constraints), return, errors, a short example, and since-version. Terse and complete.

**Architecture / ADR** — context, the decision, alternatives considered, and
consequences. Capture *why* so the next person doesn't re-litigate it. ADRs are
immutable records; supersede rather than edit.

**Runbook** — symptom → diagnosis → remediation, with copy-pasteable commands and
escalation path. Written to be used at 3 a.m. by someone who didn't build the system.

**Docstrings** — what it does, params, returns, raises, and a usage example for anything
non-trivial. Explain *why* for surprising behavior.

## Style

- Active voice, present tense, second person ("you run", not "the user should run").
- Short sentences. One idea per paragraph. Concrete over abstract.
- Front-load: the most important sentence first.
- Code blocks for anything the reader will copy. Specify the language for highlighting.

## Verify before shipping

Re-read the source and confirm every statement matches. Flag anything you couldn't
verify rather than guessing. Don't invent flags, endpoints, or behavior the code lacks.
