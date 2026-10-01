# Ticket 12: Add controlled online evaluation

## Stage

Post-MVP

## Goal

Measure routing policies on live-like traffic without hiding quality regressions behind average cost savings.

## Scope

- Define experiment cohorts and assignment rules.
- Compare a control policy with a candidate policy.
- Track verified success, quality, cost, latency, escalation, and user-visible rework.
- Add minimum sample, confidence, and stop conditions.
- Keep sensitive task content out of experiment reports.

## Acceptance criteria

- Cohort assignment is stable for the same experiment key.
- Control and candidate policies use the same task eligibility rules.
- A failing stop condition disables the candidate policy.
- The report includes uncertainty and cohort sizes.

## Validation

Run deterministic experiment simulations with injected policy differences.
