# Ticket 13: Execute independent subtasks in parallel

## Stage

Vision

## Goal

Reduce end-to-end latency by scheduling independent coding subtasks concurrently.

## Scope

- Represent task dependencies in the task graph.
- Detect ready tasks and dispatch them under a shared budget.
- Join results before dependent tasks run.
- Attribute cost, latency, and failures to both task and graph levels.
- Preserve deterministic replay of scheduling decisions.

## Acceptance criteria

- Independent fixture tasks run concurrently.
- Dependent tasks wait for required artifacts.
- Shared budgets prevent parallel work from exceeding limits.
- Graph reports show critical-path latency and total spend.

## Validation

Run scheduler tests with controlled delays, failures, and dependency graphs.
