---
name: prompt-engineering
description: >-
  Use when authoring or improving Claude Code agents, skills, slash commands, or
  CLAUDE.md instructions. Covers how to write a triggering description, structure a
  system prompt, scope tools, and apply progressive disclosure so the model
  actually uses what you build. See PATTERNS.md for operating-discipline techniques
  distilled from production agent prompts.
---

# Prompt Engineering for Claude Code

The artifacts in this toolkit — agents, skills, commands, instructions — are prompts.
They only help if the model (a) loads them at the right moment and (b) can act on them.
These two failure modes drive every guideline below.

## Descriptions decide whether you get loaded

For agents and skills, the `description` is the *only* thing the model sees when deciding
whether to invoke. Write it for triggering, not for humans:

- Start with **"Use when…"** and name the concrete situations, symptoms, and keywords a
  user would actually say.
- Include 1–2 example triggers. Specificity beats elegance.
- State what it's for *and what it's not* if there's a near neighbor (e.g. "for
  design, not implementation").
- A vague description ("helps with code") never fires. A precise one fires reliably.

## System prompts: role, method, output, boundaries

Structure the body of an agent/skill as:

1. **Role** — who it is and what it optimizes for, in one or two sentences.
2. **Method** — the concrete steps or checklist it follows. Numbered, specific.
3. **Output format** — the exact shape you want back. Models follow a template well.
4. **Boundaries** — what *not* to do, and what to do when uncertain (ask vs. assume).

Write positive instructions ("do X") over long lists of prohibitions. Show the format
with a small example rather than describing it abstractly.

## Scope tools to the job

Give an agent only the tools it needs. A reviewer or auditor is read-only (Read, Grep,
Glob, Bash) — no Edit. A refactorer needs Edit. Narrow tools reduce mistakes and make the
agent's contract obvious.

## Progressive disclosure (skills)

Keep `SKILL.md` lean — the high-frequency guidance. Push exhaustive references
(checklists, catalogs, schemas) into sibling files the model loads only when needed, and
point to them by name. This keeps the always-loaded surface small while making depth
available on demand. (See `code-review-rubric` and `refactoring-catalog` here for the
pattern.)

## Calibrate, don't overclaim

Tell the model to express uncertainty, prefer evidence over assertion, and stop and ask
when a decision is genuinely the user's. An agent that fabricates confidence is worse
than one that says "I'm not sure — here's what would confirm it."

## Operating-discipline patterns

The sections above cover *structure* — how to make an agent load and be actionable. For the
*behavioral* techniques that separate a sharp agent from a vague one (parallel tool use,
read-before-edit, verify-with-evidence, autonomy and stop conditions, output contracts,
delegation briefing), load **PATTERNS.md**. It distills what production coding agents
converge on, so you can state the right discipline in each agent's Method/Boundaries.

## Test it

After writing, sanity-check the trigger: would the description fire on a realistic
request? Would it *over*-fire on unrelated ones? Tune the description until it's sharp.
