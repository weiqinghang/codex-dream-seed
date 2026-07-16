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

## Release and installation channels

- `product` is the stable distribution branch and the GitHub default branch.
- `develop` is the active integration branch. It may contain incomplete, experimental,
  or not-yet-promoted behavior and is never the implicit installation source.
- Stable releases are immutable annotated tags. The current stable release is `v0.3.0`
  at commit `0d48bba`; the `0.4.0` line on `develop` remains development-only until it
  passes an explicit promotion decision.
- When a user asks to clone, install, initialize, upgrade, or start Dream without naming
  a channel, use the latest stable tag or `product`. Never select `develop` merely
  because it has the newest commit or the highest package version.
- Use `develop` only when the user explicitly requests development, preview, or
  pre-release behavior. Do not recreate a `main` branch as an installation fallback.
- Before promoting a new stable version, verify the complete supported OS/Python matrix,
  update the documented version, advance `product`, and create a matching immutable tag.

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
