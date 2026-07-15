# Knowledge lifecycle

Keep four independent state axes:

```text
knowledge: observed -> emerging -> established -> retired
candidate: proposed -> accepted | rejected | superseded
adoption:  planned -> applied | rolled_back
validation: pending -> validating -> proven | failed | inconclusive
```

Use one stable `KD-*` item for a durable concept. Append facts to `timeline.jsonl`, update the
current snapshot in `item.json`, and regenerate `summary.md`. Reports reference knowledge IDs;
they are not the source of truth.

Every candidate must include confidence, frequency, scope, project labels, `TASK-*` references,
observation, minimal evidence summaries, interpretation, cause, impact, recommended action,
artifact type, outline, limitations, counterexamples, and a validation plan.

Only a traceable human decision changes a candidate from `proposed`. Only accepted candidates
may gain adoption records. Starting validation requires a contract with applicability,
expected behavior, observable signals, success criteria, failure signals, target eligible task
count, and maximum validation days.

During later runs, collect eligible/invoked/compliant/outcome evidence for active validations.
No eligible task is not failure. Silence is not positive feedback. Use `inconclusive` when the
outcome cannot be attributed reliably, and require user confirmation for the final result.
