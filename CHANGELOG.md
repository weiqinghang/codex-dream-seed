# Changelog

## Unreleased

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
