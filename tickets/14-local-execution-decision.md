# Ticket 14: Choose local execution when delegation costs more

## Stage

Vision

## Goal

Decide whether a subtask should run locally instead of through a remote worker model.

## Scope

- Define local execution capabilities and resource limits.
- Estimate delegation overhead from context transfer, latency, and cost.
- Add `DO_LOCALLY` as a policy action.
- Verify local results with the same evidence path as remote results.
- Compare local and remote execution on supported task types.

## Acceptance criteria

- The policy can select `DO_LOCALLY` only for supported tasks.
- Local execution enforces time, memory, and tool budgets.
- Local and remote results share one trace schema.
- The evaluation reports quality, cost, and latency for both actions.

## Validation

Run policy and sandbox fixtures with bounded local commands.
