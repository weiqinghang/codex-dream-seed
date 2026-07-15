# Workspace schema migrations

- Treat the old workspace as read-only evidence.
- Preview before applying and write only to a new, absent target.
- Run every registered adjacent migration in version order.
- Never invent task references or human decisions; collect an explicit private
  resolution with a reason when legacy evidence is ambiguous.
- Preserve cursor fingerprints, task-tree mappings, knowledge maturity, candidate,
  adoption and validation state.
- Verify stable-ID uniqueness, allocator safety, lifecycle references, record counts and
  privacy before switching workspaces.
- Keep source and target until the user accepts the migrated workspace. Rollback is a
  return to the unchanged source, not an inferred down migration.
- A squashed fast path is acceptable only when it is a separately released and tested
  migration whose output is proven equivalent to the adjacent chain.
