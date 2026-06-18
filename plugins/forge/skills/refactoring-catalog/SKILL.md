---
name: refactoring-catalog
description: >-
  Use when improving the structure of existing code without changing behavior —
  identifying code smells and applying the right named refactoring safely. Covers
  the discipline of behavior-preserving change; see CATALOG.md for the smell→fix
  reference.
---

# Refactoring Catalog

Refactoring changes the shape of code while preserving its behavior exactly. Behavior
preservation is the contract — if you can't verify it, you can't ship the refactor.

## The discipline

1. **Safety net first.** Confirm tests exist and pass for the code you'll touch. No
   coverage? Write characterization tests that pin current behavior before changing it.
2. **Small, reversible steps.** One named transformation at a time. Run tests after each.
   Each step keeps the code working — never a long red period.
3. **Separate refactoring from behavior change.** A refactor adds no features and fixes no
   bugs. Found a bug? Note it; fix it in its own commit so the diff stays honest.
4. **Justify each change.** Each step reduces a concrete problem — duplication, a long
   function, tangled conditionals, an unclear name. No abstraction without a second call
   site. Don't refactor for taste alone.

## Recognizing when to refactor

Refactor when the code is about to be changed and its current shape makes the change
hard — not on a schedule, and not while also adding a feature in the same step. The
"two hats": you're either adding behavior *or* refactoring, never both at once.

## Smell → refactoring

Common smells and their fixes are in **CATALOG.md**. The headline ones:

- **Long function** → Extract Function until each does one thing.
- **Duplicated code** → Extract Function/Class; pull up to a shared place — but only if
  the cases are *truly* the same (beware false DRY coupling unrelated code).
- **Long parameter list** → Introduce Parameter Object; Preserve Whole Object.
- **Nested conditionals / arrow code** → Guard Clauses; Replace Conditional with
  Polymorphism.
- **Feature envy / inappropriate intimacy** → Move Function/Field to the class it talks
  to most.
- **Primitive obsession** → Replace primitive with a small value type.
- **Mysterious name** → Rename (the highest-value, lowest-risk refactoring).

## Verify

Run the full relevant suite after the change and confirm it's green and that the diff
reads as behavior-preserving. If you can't prove behavior is unchanged, stop — an
unverifiable refactor is just a risky edit.
