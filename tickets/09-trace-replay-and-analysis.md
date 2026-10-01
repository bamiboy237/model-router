# Ticket 09: Build trace replay and analysis

## Stage

Post-MVP

## Goal

Reproduce routing decisions and compare policy versions without calling providers.

## Scope

- Store immutable execution traces with schema and policy versions.
- Replay routing decisions from a trace and a model catalog snapshot.
- Add reports for verified success, quality, cost, latency, escalation, context tokens, cache hits, and regret.
- Support cohort analysis by task type, language, repository shape, and failure history.

## Acceptance criteria

- Replay reproduces the recorded decision for a deterministic policy.
- Reports identify the data and policy versions used.
- Analysis separates provider execution results from policy counterfactuals.
- Sensitive prompt content is excluded or redacted from reports.

## Validation

Run replay tests and compare reports with known fixture outputs.
