# GitHub Task Ledger

Forge can keep a local Markdown ledger offline or synchronize it with GitHub Issues. Pick
one authority for a project. Local authority is the default and GitHub authority is an
explicit import/status mode; the sync engine never performs silent last-write-wins merges.

## Commands

From a repository containing `.forge/tasks/`:

```bash
python3 scripts/forge-tasks.py --repo AlisinaDevelo/md-files --json plan
python3 scripts/forge-tasks.py --repo AlisinaDevelo/md-files --json apply --yes
python3 scripts/forge-tasks.py --repo AlisinaDevelo/md-files --json status
python3 scripts/forge-tasks.py --repo AlisinaDevelo/md-files --authority github --json import
python3 scripts/forge-tasks.py --repo AlisinaDevelo/md-files --authority github --json import --write
```

`plan` is read-only. `apply` is the only command that mutates GitHub and it requires
`--yes`. Every successful mutation is persisted to `.forge/github-sync.json` and emits a
privacy-safe idempotent event to `.forge/receipts.jsonl`; use `--receipts PATH` to choose a
different evidence file.

## Identity and mapping

Each managed issue contains a hidden marker of the form
`<!-- forge-task:v1 id=... sync=... -->`. The task ID is the stable identity across
machines, issue renames, imports, retries, and local filename changes. The sync hash is the
last shared content baseline. Issue titles and bodies carry status, agent, model tier,
dependencies, parent, release target, goal, acceptance criteria, context, and notes.

Parent tasks use GitHub's native sub-issue relationship. `depends_on` uses GitHub's native
blocked-by relationship. The graph is never flattened into labels or checklists. A first
sync creates issues first; run `plan` again to resolve native relationships after GitHub
has assigned issue IDs.

## Conflicts and recovery

When both local Markdown and the managed issue changed from the same sync baseline, `plan`
returns a structured `conflict` operation and `apply` refuses to write. Resolve the task
manually in the authority you choose, update the other side, then plan again. Do not delete
the marker while resolving; it is the duplicate-prevention key.

The state file records completed operation IDs after each mutation. A retry skips completed
operations, re-discovers issues created before a process interruption, and checks native
relationships before adding them again. If a saved issue number no longer exists, the plan
shows an explicit recreation reason and reuses the same hidden task ID. A renamed repository
fails before issue scanning so a stale `--repo` cannot write elsewhere.

Pagination is bounded at 100 pages. GitHub API failures preserve the HTTP status and API
path in machine-readable errors, including insufficient scopes and rate-limit responses.
The backend requires the repository Issues write permission for apply and the normal `gh`
authentication for reads. Projects are not required: this backend deliberately does not
request Projects scopes or mutate Projects, while preserving release/status data in the
issue body for a future configured Projects adapter.

## Disconnecting safely

To stop synchronization, stop running `apply` and remove or archive `.forge/github-sync.json`
and `.forge/receipts.jsonl` according to your retention policy. Existing GitHub Issues are
not deleted or rewritten by disconnecting. To keep local-only operation, omit `--repo` and
continue using the Markdown ledger and orchestration skills.

The implementation is the standard-library backend at
`plugins/forge/skills/task-ledger/scripts/forge-tasks.py`; the root script is only a
convenience wrapper.
