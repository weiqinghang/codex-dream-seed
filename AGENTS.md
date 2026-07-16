# Codex Dream Seed contributor contract

This repository is the distributable engine and skill source. It must remain free
of real user sessions and previously generated dream results.

## Boundaries

- Use synthetic rollout fixtures in tests. Never read `~/.codex/sessions` during tests.
- Never commit real session UUIDs, absolute local paths, raw messages, capsules,
  knowledge items, reports, tokens, cookies, or credentials.
- Keep mutable user data in a separately initialized workspace.
- Treat `state/` as private. Only sanitized `knowledge/` and `reports/` may be shared.
- Do not advance a review cursor until semantic review artifacts have been persisted.
- Do not accept, apply, reject, or validate a candidate without a traceable human decision.

## Architecture

- `codex_dream/` is the deterministic data plane.
- `skills/codex-dream/` is the optional semantic control plane.
- A user-created workspace owns runtime state and learned knowledge.

## Bootstrap and first run

When the user asks to install, initialize, or start Dream from a fresh clone:

1. Run `python3 scripts/bootstrap.py` (`py scripts\bootstrap.py` on Windows) and inspect
   the read-only plan.
2. If the plan targets an empty directory, an existing Dream workspace, and this checkout's
   bundled Skill, continue with `--apply` under the user's installation request. Stop on a
   non-empty non-Dream target or any unexpected external path.
3. Default new personal workspaces to `~/Documents/codex-dream-workspace`. Preserve an
   already configured valid workspace unless the user explicitly requests migration.
4. Report the `doctor` result and the 30-day dry-run inventory. Never establish the first
   ledger or read semantic session content until the user confirms the previewed scope.
5. Tell the user to restart Codex after a new or upgraded Skill installation.

Run `python3 -m unittest discover -s tests -v` and validate the bundled Skill
before committing changes.
