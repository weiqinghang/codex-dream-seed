# Privacy boundary

Assume every rollout contains sensitive data.

Keep the following only in ignored `state/`: real session UUIDs, rollout paths, absolute project
paths, raw messages, private capsules, and the `TASK-*` mapping. Never quote credentials or
unnecessarily reproduce business data in tool output.

Only sanitized knowledge items and reports may enter Git. Their evidence must use stable
`TASK-*` references and minimal summaries. Do not write session UUIDs, `/Users/...`,
`/home/...`, `C:\Users\...` or UNC paths, `.codex` rollout locations, tokens, cookies,
passwords, or raw transcripts.

Run `codex-dream --workspace <path> privacy-audit` before checkpointing and before committing
shareable artifacts. Treat any finding as fail-closed: inspect and redact it; never suppress a
finding merely to finish the run.

Do not upload session data or use network services during review without explicit user approval.
