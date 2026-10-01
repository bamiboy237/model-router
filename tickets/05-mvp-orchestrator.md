# Ticket 05: Build the orchestrator harness

## Stage

MVP. Starts after ticket `03b` is complete.

## Goal

Run a coding goal through an orchestrator agent that delegates bounded subtasks to subagents through the router.

## Design

```text
User goal
  │
  ▼
Orchestrator agent (Pydantic AI)
  ├── read-only repo tools: list_files, read_file, search
  ├── delegate(task) ──► router ──► worker in a Docker sandbox ──► verify ──► retry / escalate
  └── report_outcome(attempt, verdict, ...)
```

- The orchestrator only delegates. It reads the repository to plan, but it does not edit code. Doing small work itself is ticket `14`.
- `delegate` wraps `model_router.escalation.run_task`. It returns the stop reason, the checks, the cost, the receipt, and the patch to the orchestrator.
- `report_outcome` records the orchestrator's review, or a user comment it relays, as a feedback event.
- The orchestrator applies accepted patches to its own working copy, so later subtasks build on earlier ones.

## Scope

- Accept a coding goal and create bounded subtasks with kinds, domains, files, and checks.
- Build a minimal context packet for each subtask.
- Route, run, verify, and escalate each subtask with a per-task budget, plus a budget for the whole goal.
- Persist the task graph, the traces, and the feedback events.
- Run goals in the lab, and compare the result with the always-strongest baseline.

## Acceptance criteria

- A fixture goal completes through multiple task kinds.
- Each subtask has a bounded context and budget.
- A failed subtask can escalate without losing task lineage.
- The final report includes verified success, cost, latency, and escalation count.
- The MVP reaches verified success comparable to the always-strongest baseline at lower total cost on the lab's fixture goals.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script with a scripted orchestrator and scripted workers on a fixture goal.
