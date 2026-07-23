---
name: codex-dream
description: Incrementally review local Codex sessions as task trees, preserve effective practices, identify reusable work and shorter alternatives to detours, and maintain evidence-backed candidate knowledge without exposing private rollout data. Use when the user asks to "开始做梦", review recent Codex collaboration, build or update a Dream baseline, inspect pending session increments, generate a periodic Dream report, or collect validation evidence for previously adopted improvements.
---

# Codex Dream

Use the installed `codex-dream` commands as the deterministic data plane. Keep semantic
judgment in this workflow and mutable data in the user's initialized workspace.

Use [references/operating-handbook.md](references/operating-handbook.md) as the canonical
user-facing semantics source. Read only the relevant section: sections 1-2 for a first Dream, section 5 for Console
handoff, section 6 for validation/closeout, and section 7 for recovery. Do not duplicate or
silently redefine the five board states in this Skill.

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
5. Before reading sessions or calling `run-start`, obtain one lightweight focus response. If
   the initiating message already states the project, stage, felt result, and expected result,
   treat it as the response and do not ask the same question again. Otherwise ask in the user's
   current language. For a Chinese conversation, ask:

   > 开始前，最近的实践中，有没有哪个项目、哪个环节让你明显觉得做得很好，值得保留；
   > 或者做得不好，不符合你的预期？请告诉我项目、环节、你的实际感受和原本预期。
   > 如果没有特别关注，可以说“没有，按默认范围做梦”。

   Translate the same meaning for other languages without adding more questions. Ask this when
   the user's initial instruction is only "开始做梦". Do not replace the question with the
   agent's own ranking of what seems important.
6. Convert the response into a compact `user_anchor`, restate it with the time range, project
   scope, and exclusions, and allow the user to correct it. Ask at most one follow-up when a
   material field cannot be represented without guessing. A user who states no special focus
   has answered the gate; do not force a longer interview.
7. On the first run, execute a 30-day dry-run preview and stop for confirmation before
   writing the ledger. After confirmation, establish the 30-day ledger but review only
   the latest 7 days first.
8. For an established V2 workspace, start a tracked `DREAM-*` cycle only after the
   `user_anchor` and remaining scope are confirmed. Link only task references actually
   reviewed, and complete the cycle only after its sanitized report is persisted and passes
   privacy audit.

Keep real sessions and Dream results out of the distributable seed repository. If invoked
from the seed source tree, use the resolved external workspace for every mutable artifact.
Default a new workspace to `~/Documents/codex-dream-workspace` unless the user chooses a
different location.

## Resume decisions made in Dream Console

Dream Console is a deterministic review and decision companion. It does not call a model,
perform semantic work, edit target projects, or claim that an experiment has started. Codex
is the only semantic control plane.

When the user asks to continue an item confirmed in Dream Console, use the exact `ACT-*`,
workspace fingerprint, and attempt copied from the Console instruction. Run the checks in
this order:

```bash
codex-dream doctor
codex-dream console-context --handoff <ACT-*> --expect-fingerprint <ws-*> --expect-attempt <n>
codex-dream handoff-claim <ACT-*> --expect-fingerprint <ws-*> --expect-attempt <n>
```

Fail closed on any Workspace, state, or attempt mismatch. Never choose a handoff by recency or
replace the copied instruction with a bare `handoff-list`/`handoff-claim` sequence. Restate the
specified handoff's confirmed scope and success criteria briefly, then claim it before changing
any project or knowledge state. Do not expose raw private session content.

Do not ask the user to reconfirm fields already recorded in the handoff unless the target is
missing, the plan is stale, the requested carrier conflicts with repository policy, or an
external write needs authority that the Console decision did not grant. A Console decision
authorizes only the stated trial plan; it does not broaden the target or scope.

After claiming, use the ordinary knowledge lifecycle commands to create the adoption and
validation records, and perform only the authorized work. Then write a compact, structured
result back to the handoff:

```bash
codex-dream handoff-complete <ACT-*> --result \
  '{"outcome":"trial_started","adoption_id":"ADP-*","validation_id":"VAL-*"}'
```

If execution cannot continue, use `codex-dream handoff-fail <ACT-*> --error <reason>` so the
Console can surface the failure for human review. Completing a handoff means Codex processed
the request; it does not mean the improvement is proven or fully implemented. Those claims
remain governed by adoption and validation state.

If `doctor` reports `migration_required`, stop normal Dream writes and use the CLI's
`migrate` dry-run against a new target workspace. Execute the registered adjacent
migration chain in order; do not combine steps ad hoc. Require explicit private
resolutions for ambiguous legacy records, apply only when `can_apply` is true, then run
`verify` before switching the user to the new workspace. See
`references/schema-migrations.md`.

## Build the review batch

Start the cycle with `codex-dream run-start --title <title> --scope <json>`. The scope must
include one of these forms:

```json
{
  "user_anchor": {
    "status": "provided",
    "captured_from": "user_response",
    "project": "project or cross-project",
    "stage": "the relevant stage",
    "polarity": "positive | negative | mixed",
    "felt_result": "the user's experience",
    "expected_result": "the user's expectation"
  }
}
```

```json
{
  "user_anchor": {
    "status": "none",
    "captured_from": "user_response",
    "reason": "the user explicitly selected the default review"
  }
}
```

The second form means the user explicitly chose the default review; it is not permission to
skip the question. Preserve the returned `DREAM-*` ID for the report and final checkpoint.

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

Treat the user anchor as the primary investigation hypothesis, not a predetermined conclusion.
Spend the main review attention on evidence that supports, qualifies, or contradicts it. Keep a
background scan for sufficiently important chronic or cross-project patterns so the anchor does
not hide accumulated problems.

## Persist before checkpointing

For each review unit:

1. Record observations and candidates with stable `TASK-*` evidence references.
2. Update an existing knowledge item when the pattern already exists; do not create a
   duplicate title for new evidence.
   When proposing a candidate, also persist deterministic ranking inputs when available:
   recent and cumulative trigger counts, persistence days, value impact, and detour cost.
3. Write the sanitized report or knowledge artifact.
4. Run `codex-dream privacy-audit`.
5. Only after the artifact exists and passes the audit, checkpoint every rollout actually
   reviewed with a private redacted capsule and linked observation IDs.

Never checkpoint merely because a task is quiet or long enough. Never count sibling
sub-agents as independent repetitions.

After checkpointing, link the reviewed `TASK-*` references with `codex-dream run-link`.
Complete the cycle with `codex-dream run-complete --report <reports/...> --summary <json>`.
When the host exposes exact usage counters for the Dream cycle, persist them under
`summary.run_metrics.token_usage` using `input_tokens`, `cached_input_tokens`,
`output_tokens`, and `total_tokens`. Omit unavailable fields and never estimate historical
Token usage. Console derives elapsed time from the tracked start and completion timestamps.
For a provided anchor, `summary.user_anchor_result` must record the relationship status,
supporting and counterevidence `TASK-*` references, and any evidence gap. Use one of
`aligned`, `partially_aligned`, `conflicting`, or `insufficient_evidence`. For a `none` anchor,
record `{"status":"not_applicable","reason":"user selected the default review"}`. Do not
complete a cycle whose report is missing, whose assessment references an unlinked task, or whose
report has not passed privacy audit.

## Stop at the human gate

Create and update only `proposed` candidates unless the user supplies a traceable decision.
Do not modify external projects, install generated Skills, edit `AGENTS.md`, schedule jobs,
or apply candidates during a Dream run. Present at most five high-value candidates and wait
for the user to enter a confirmed trial, reject, defer, or request more evidence. The visible
five are an attention window, not the complete candidate pool. Rank both acute recent signals
and chronic recurring problems so an older unresolved issue can return to the attention window
after accumulating enough burden.
