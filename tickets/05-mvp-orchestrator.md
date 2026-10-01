# Ticket 05: Connect the MVP orchestrator

## Stage

MVP

## Goal

Execute a coding goal as a bounded task graph through routing, verification, escalation, and trace storage.

## Scope

- Accept a coding goal and create bounded subtasks.
- Build a minimal context packet for each subtask.
- Route each subtask through the rule-based router.
- Run verification and escalation.
- Persist the task graph and final execution trace.
- Compare the result with the always-strongest baseline.

## Acceptance criteria

- A fixture goal completes through multiple task types.
- Each subtask has a bounded context and budget.
- A failed worker result can escalate without losing task lineage.
- The final report includes verified success, cost, latency, and escalation count.
- The MVP meets the README success criterion on the fixture suite.

## Validation

Run an end-to-end test with deterministic workers, verifiers, and trace storage.
