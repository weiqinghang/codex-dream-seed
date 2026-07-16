---
name: codex-dream
description: Incrementally review local Codex sessions as task trees, preserve effective practices, identify reusable work and shorter alternatives to detours, and maintain evidence-backed candidate knowledge without exposing private rollout data. Use when the user asks to "开始做梦", review recent Codex collaboration, build or update a Dream baseline, inspect pending session increments, generate a periodic Dream report, or collect validation evidence for previously adopted improvements.
---

# Codex Dream

Use the installed `codex-dream` commands as the deterministic data plane. Keep semantic
judgment in this workflow and mutable data in the user's initialized workspace.

If the data-plane command is missing while working from a fresh seed checkout, follow the
repository `AGENTS.md` and run `python3 scripts/bootstrap.py` before attempting a Dream run.
On Windows, use `py scripts\bootstrap.py`. After applying the reviewed bootstrap plan, ask
the user to restart Codex so the installed Skill becomes discoverable in new sessions.

## Establish scope

1. Resolve the workspace with `codex-dream doctor`. The CLI uses an explicit
   `--workspace`, `CODEX_DREAM_WORKSPACE`, an initialized workspace containing the current
   directory, then the machine default registered by `codex-dream set-default`.
2. Read the resolved workspace's `dream.toml` and confirm `doctor` reports `status: ok`.
3. If resolution fails, stop and ask the user to select or initialize a workspace. Never
   initialize the current project merely because the command was invoked there.
4. Treat the current directory as instruction context, not storage selection. It does not
   restrict review to the current project unless the user explicitly requests that scope.
5. State the time range, project scope and exclusions before reading sessions.
6. On the first run, execute a 30-day dry-run preview and stop for confirmation before
   writing the ledger. After confirmation, establish the 30-day ledger but review only
   the latest 7 days first.

Keep real sessions and Dream results out of the distributable seed repository. If invoked
from the seed source tree, use the resolved external workspace for every mutable artifact.
Default a new workspace to `~/Documents/codex-dream-workspace` unless the user chooses a
different location.

If `doctor` reports `migration_required`, stop normal Dream writes and use the CLI's
`migrate` dry-run against a new target workspace. Execute the registered adjacent
migration chain in order; do not combine steps ad hoc. Require explicit private
resolutions for ambiguous legacy records, apply only when `can_apply` is true, then run
`verify` before switching the user to the new workspace. See
`references/schema-migrations.md`.

## Build the review batch

Run:

```bash
codex-dream --since-days <days> sync
codex-dream --since-days <days> pending
codex-dream-review
```

Pass `--workspace <path>` only for an intentional one-run override. Do not infer a
current-project-only review from the shell working directory.

Treat a parent rollout and native sub-agent rollouts as one review unit. Load only the
saved capsule, the configured overlap, new events, and linked observation IDs. For a
`reconcile` item, reread the affected rollout rather than trusting the old cursor.

Read [references/review-protocol.md](references/review-protocol.md) before semantic
review. Read [references/privacy.md](references/privacy.md) before writing shareable
artifacts. Read [references/knowledge-lifecycle.md](references/knowledge-lifecycle.md)
when creating or updating knowledge. Read [references/report-format.md](references/report-format.md)
when producing a cycle report.

## Persist before checkpointing

For each review unit:

1. Record observations and candidates with stable `TASK-*` evidence references.
2. Update an existing knowledge item when the pattern already exists; do not create a
   duplicate title for new evidence.
3. Write the sanitized report or knowledge artifact.
4. Run `codex-dream privacy-audit`.
5. Only after the artifact exists and passes the audit, checkpoint every rollout actually
   reviewed with a private redacted capsule and linked observation IDs.

Never checkpoint merely because a task is quiet or long enough. Never count sibling
sub-agents as independent repetitions.

## Stop at the human gate

Create and update only `proposed` candidates unless the user supplies a traceable decision.
Do not modify external projects, install generated Skills, edit `AGENTS.md`, schedule jobs,
or apply candidates during a Dream run. Present a small set of high-value candidates and
wait for the user to accept, reject, continue observing, or request more evidence.
