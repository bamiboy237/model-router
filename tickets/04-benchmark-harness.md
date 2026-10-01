# Ticket 04: Build the benchmark harness

## Stage

MVP

## Dependencies

Ticket `03b` delivers trial execution in the `trial_lab` package. This ticket defines the benchmark manifest and builds the baseline reports from the lab's exported trial records.

## Goal

Produce comparable outcomes for every eligible `(task, model)` pair.

## Scope

- Define a benchmark manifest and task fixtures.
- Run each fixture against selected models with the same context packet.
- Save outcomes, verifier evidence, cost, latency, and task identity.
- Report always-cheapest, always-strongest, lowest-latency, and rule-router baselines.
- Separate benchmark definition, run identity, and observed outcome.

## Acceptance criteria

- The harness produces a machine-readable dataset.
- Re-running a benchmark preserves task identity and records a new run.
- The report compares success, quality, cost, and latency by policy.
- Held-out tasks are excluded from routing configuration and training data.

## Validation

Run the harness against mocked workers and a small local fixture suite.
