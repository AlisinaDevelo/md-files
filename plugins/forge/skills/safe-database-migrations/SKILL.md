---
name: safe-database-migrations
description: >-
  Use when writing or reviewing a database schema migration, especially on a live
  system. Covers the expand/contract pattern for zero-downtime changes, avoiding
  long locks, safe backfills, and always having a rollback path.
---

# Safe Database Migrations

A migration runs against live data with live traffic. The goals: no downtime, no data
loss, and a way back if it goes wrong. Schema changes are the highest-risk routine
operation most teams perform — treat them with care.

## The expand/contract pattern

Never make a breaking schema change in one step. Split it across deploys so old and new
code both work at every point:

1. **Expand** — add the new structure, backward-compatible. New nullable column, new
   table, new index (built concurrently). Old code ignores it.
2. **Migrate** — backfill data in **batches** (not one giant `UPDATE`), and deploy code
   that writes to both old and new (dual-write) while still reading old.
3. **Switch** — deploy code that reads from the new structure.
4. **Contract** — once nothing references the old structure, add constraints
   (NOT NULL after backfill) and drop the old column/table in a later deploy.

Each step is independently deployable and reversible.

## Avoid long locks

- Adding a NOT NULL column with a default can rewrite the whole table on some engines —
  add nullable, backfill, then set the constraint.
- Build indexes concurrently / online where the engine supports it.
- Backfill in bounded batches with a short pause; a single large transaction holds locks
  and bloats replication lag.
- Know your engine's locking semantics for each DDL operation before you run it.

## Always have a rollback

Every forward migration needs a tested `down`, or an explicit, documented reason it's
irreversible (and then: backup first). A dropped column or table is not reversible —
treat destructive steps as one-way doors and gate them behind a verified, idle period.

## Before running on production

- Test on a copy with **realistic data volume** — a migration that's instant on 100 rows
  can lock a table for minutes on 100M.
- Estimate lock duration and replication impact.
- Make data migrations idempotent and resumable so a mid-run failure can be retried.
- Separate schema changes from data changes from code deploys where possible.

## Red flags in review

A single `UPDATE` over a huge table · `ALTER TABLE` that rewrites in place under load ·
NOT NULL added before backfill · a `down` migration that loses data silently · no batch
size on a backfill · dropping a column in the same deploy that stops using it.
