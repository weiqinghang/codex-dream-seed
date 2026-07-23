# Schema migration protocol

Codex Dream versions the persisted workspace contract independently from the Python
package. A schema version changes only when existing knowledge or runtime state needs a
different durable representation.

## Canonical upgrade path

1. Every registered step connects exactly one adjacent pair: `N -> N+1`.
2. The engine discovers the source version and plans the complete ordered chain.
3. The source is hashed and remains read-only.
4. The engine copies supported assets into a new staging workspace.
5. Steps run in order. Each step owns its deterministic transforms and explicit
   resolution requirements.
6. The final workspace is checked for schema compatibility, referential integrity,
   globally unique stable IDs, ID allocator safety, lifecycle preservation, counts and
   privacy.
7. Only a fully verified staging workspace is atomically renamed to the new target.

The target must not exist. Rollback means retaining the unchanged source and deleting or
ignoring the failed staging directory; down migrations are not inferred.

## Why steps are not merged at runtime

Intermediate migrations can contain semantic decisions, repairs and invariants that are
not visible from the final file shape. Runtime script fusion would create a new untested
migration and weaken auditability. Codex may explain the plan, collect explicit
resolutions, execute the chain and diagnose a stopped step, but it must not rewrite the
canonical chain ad hoc.

A fast path is allowed only as a released artifact with fixtures proving that its output
and invariants are equivalent to the canonical chain for every supported starting
version. The adjacent chain remains the reference implementation and recovery path.

## V0 to V1

V0 denotes the original unversioned project workspace. V1:

- adds explicit workspace and knowledge schema versions;
- converts legacy candidate artifact and session fields to `suggested_artifact` and
  private `TASK-*` references;
- adds observation task references;
- records decision provenance;
- normalizes the validation time-window field;
- repairs duplicate observation IDs deterministically;
- appends one `schema_migrated` event per knowledge item;
- preserves session cursors, task maps, maturity, candidate decisions, adoptions,
  validations and sanitized reports.

Ambiguous records require a private resolution file with a reason. Missing provenance is
never fabricated merely to make migration succeed.

## Workspace V1 to V2

V2 changes the private runtime representation without changing knowledge schema V1:

- imports session ledger records, review cards and task references into
  `state/dream.sqlite3`;
- enables WAL, foreign keys, integrity checking and transactional local writes;
- introduces first-class `DREAM-*` cycles, run/task links and `ACT-*` user-action audit;
- restores existing weekly reports as historical dream cycles without inventing scope;
- moves the three source JSONL files to `state/legacy-v1/` in the target workspace;
- keeps sanitized `knowledge/` and `reports/` as readable, Git-reviewable files.

The source remains unchanged. SQLite and the archived JSONL counts must match before the
target can pass verification. After cutover, SQLite is authoritative for private runtime
state; the archived JSONL files are recovery evidence and are never dual-written.
