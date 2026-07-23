# Changelog

## 0.4.0 - 2026-07-23

- Introduce Workspace Schema V2 with a transactional SQLite private runtime store while
  preserving sanitized knowledge and reports as readable files.
- Add source-preserving V1 to V2 migration, archived JSONL recovery evidence, historical
  report import and database integrity/count verification.
- Add first-class Dream cycles, task links and traceable local user-action audit records.
- Deliver the five-state local Dream Console journey from first-run guidance through
  human decisions, guarded Codex handoff, retry, validation and closeout.
- Add fail-closed `ACT-*`/Workspace fingerprint/attempt checks, cross-process Workspace
  locking, safe report reading and deterministic Console service management.
- Add canonical Chinese-first operating guidance, partial-refresh recovery, responsive
  browser behavior and synthetic end-to-end acceptance evidence.
- Promote Python 3.9–3.13 on macOS, Linux and Windows as the tested support matrix.

## 0.3.0 - 2026-07-16

- Add a cross-platform, read-only-by-default bootstrap for clone-time CLI installation,
  atomic Skill installation, workspace initialization and first-run preview.
- Default new personal workspaces to `~/Documents/codex-dream-workspace`.
- Support Windows permission behavior and detect Windows user and rollout paths in privacy
  audits; add macOS, Linux and Windows CI coverage.
- Resolve the same default Dream workspace from any project directory through an explicit
  argument, environment override, enclosing workspace or machine-level pointer.
- Add `set-default`, `show-default` and `init --set-default` commands.
- Fail closed instead of silently treating an ordinary project directory as Dream storage.
- Align all three CLIs and the bundled Skill with the same workspace-selection contract.

## 0.2.0 - 2026-07-15

- Version workspace and knowledge persistence independently from the package.
- Add fail-closed compatibility checks and registered adjacent migrations.
- Add a real V0 to V1 migration with dry-run, explicit legacy resolutions, staging,
  invariant verification and source-preserving rollback.
- Preserve private review progress and all four knowledge lifecycle axes during migration.
- Repair duplicate legacy observation IDs with an auditable deterministic remap.
- Add V1 knowledge and lifecycle schemas plus migration guidance for the bundled Skill.
- Package migration submodules in installable distributions.

## 0.1.0 - 2026-07-14

- Publish the reusable local-first Codex Dream engine, workspace model and optional Skill.
