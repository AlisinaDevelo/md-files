# Smell → Refactoring Reference

A working catalog of code smells and the named refactorings that address them. Apply in
small steps with a green test suite between each.

## Bloaters

| Smell | What it looks like | Refactoring |
|-------|--------------------|-------------|
| Long Function | does many things; hard to name | Extract Function; Decompose Conditional |
| Large Class | too many responsibilities/fields | Extract Class; Extract Subclass |
| Long Parameter List | 4+ params, easy to misorder | Introduce Parameter Object; Preserve Whole Object |
| Primitive Obsession | strings/ints encoding domain concepts | Replace Primitive with Object; Introduce Value Type |
| Data Clumps | the same group of fields travels together | Extract Class; Introduce Parameter Object |

## Change preventers

| Smell | What it looks like | Refactoring |
|-------|--------------------|-------------|
| Divergent Change | one class changes for many reasons | Split Phase; Extract Class |
| Shotgun Surgery | one change touches many classes | Move Function/Field to consolidate |
| Parallel Inheritance | every subclass here needs one there | Move/Merge hierarchies |

## Couplers

| Smell | What it looks like | Refactoring |
|-------|--------------------|-------------|
| Feature Envy | method uses another object's data more than its own | Move Function |
| Inappropriate Intimacy | classes reach into each other's internals | Move Function/Field; Hide Delegate |
| Message Chains | `a.b().c().d()` | Hide Delegate; Extract Function |
| Middle Man | class only delegates | Remove Middle Man; Inline |

## Dispensables

| Smell | What it looks like | Refactoring |
|-------|--------------------|-------------|
| Duplicated Code | same logic in 2+ places | Extract Function; Pull Up Method |
| Dead Code | unreachable / unused | Delete it |
| Speculative Generality | abstraction with one use | Collapse Hierarchy; Inline; Remove Parameter |
| Comments (explaining what) | a comment compensating for unclear code | Extract Function with an intention-revealing name; Rename |

## Conditionals & flow

| Smell | What it looks like | Refactoring |
|-------|--------------------|-------------|
| Nested/Arrow Code | deep `if` nesting | Replace Nested Conditional with Guard Clauses |
| Complex Conditional | tangled boolean logic | Decompose Conditional; Consolidate Conditional Expression |
| Type-code Switch | `switch` on a type field repeated everywhere | Replace Conditional with Polymorphism |
| Repeated Null Checks | nil checks scattered around | Introduce Special Case / Null Object |

## Naming & clarity (highest value, lowest risk)

- **Mysterious Name** → Rename Function/Variable/Field. A good name removes the need for
  a comment and is the cheapest large improvement in readability.
- **Magic Number/String** → Replace with a named constant.

## Caution: false DRY

Removing duplication couples the deduplicated callers. Only unify code that changes for
the *same reason*. Two snippets that happen to look alike today but serve different
purposes should stay separate — premature deduplication is its own smell.
