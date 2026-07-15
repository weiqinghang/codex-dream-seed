# Review protocol

## Evidence unit

Use one parent/sub-agent task tree as one independent case. Evaluate both the root work and
delegation quality: task packet, decomposition, duplicated investigation, result absorption,
and final verification.

Exclude tasks that are too short, contain no meaningful objective, or lack enough evidence.
Do not infer outcomes from titles. Use the rollout events and, only when needed, read-only
project evidence such as instructions, diffs, tests and delivered artifacts. Preserve the
historical distinction when current project state differs from what was true in the session.

## Three finding types

### Effective practice

Separate the observed action from the interpretation. Name the task and constraint, the exact
practice, evidence of effectiveness, applicability boundaries, and whether to observe, reuse,
or propose an artifact. Success alone does not prove the process was good.

### Reusable work

Require at least two independent cases before calling work repeated. Separate stable steps from
variable inputs. Prefer a Skill for contextual multi-step judgment, a script or checker for
deterministic work, an Agent rule for durable behavior constraints, and a template for reusable
structure. State what the abstraction saves and what flexibility it loses.

### Detour improvement

Reconstruct the shorter path using information available at the time. Classify the cause as
`user_instruction`, `agent_behavior`, `environment`, or `mixed`. Give a concrete replacement
instruction, sequence, rule, Skill outline, script, template, or check.

## Maturity

- `observed`: one case; retain evidence without claiming a pattern.
- `emerging`: at least two independent cases; begin relating evidence.
- `established`: usually at least three cases with clear applicability boundaries.
- `retired`: obsolete, superseded, or no longer worth maintaining.

Use `once` for a high-impact single event. Do not promote a cross-project or global capability
without evidence from at least two projects. Preserve counterexamples and resolve conflicting
successful practices by applicability conditions rather than forced uniformity.
