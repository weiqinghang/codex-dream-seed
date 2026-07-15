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

Run `python3 -m unittest discover -s tests -v` and validate the bundled Skill
before committing changes.
