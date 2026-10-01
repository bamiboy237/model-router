# Ticket 03: Verify work and escalate failures

## Stage

Beginning

## Goal

Use external evidence to accept, retry, or escalate worker results.

## Scope

- Add verifier interfaces for command-based checks and task-specific evaluators.
- Accept results only when required checks pass.
- Escalate failed or uncertain results to an eligible stronger worker.
- Enforce attempt, cost, and latency budgets.
- Record the full attempt chain in the execution trace.

## Acceptance criteria

- A passing verifier accepts a result.
- A failing verifier triggers escalation when a stronger worker is available.
- The system stops when the escalation budget is exhausted.
- The trace reports cumulative cost and latency across attempts.

## Validation

Run tests with deterministic worker and verifier fixtures.
