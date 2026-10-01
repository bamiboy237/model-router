# Ticket 16: Expose the routing control plane

## Stage

Vision

## Goal

Expose decisions, evidence, budgets, policies, and model status through an operator interface.

## Scope

- Add read APIs for model catalog, policy versions, decision receipts, traces, and evaluation reports.
- Add guarded actions for policy promotion, rollback, experiment stop, and model disablement.
- Enforce operator authorization and action audit records.
- Provide task-level and cohort-level quality, cost, latency, and escalation views.
- Keep user content redacted from operator views by default.

## Acceptance criteria

- Operators can inspect why a decision was made.
- Operators can promote, roll back, and disable policies or models through guarded actions.
- Every mutating action has an audit record.
- Unauthorized actions fail without changing routing state.

## Validation

Run API contract, authorization, redaction, and rollback tests.
