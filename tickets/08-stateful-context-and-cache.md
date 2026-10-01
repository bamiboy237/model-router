# Ticket 08: Add stateful context and cache decisions

## Stage

Post-MVP

## Goal

Use task history, context cost, and cache affinity in routing decisions.

## Scope

- Store session state, task lineage, prior attempts, and context references.
- Build minimal context packets from durable state.
- Measure context transfer and cache reuse.
- Add context and cache penalties to the policy.
- Compare stateless and stateful policies on the benchmark suite.

## Acceptance criteria

- The context builder sends only references and artifacts needed by the task.
- The policy can prefer an existing task-cluster worker when evidence supports it.
- The trace records context size and cache assumptions.
- The report shows quality, cost, and latency effects of stateful routing.

## Validation

Run controlled benchmark scenarios with fixed cache and session-state fixtures.
