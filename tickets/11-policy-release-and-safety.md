# Ticket 11: Release policies safely

## Stage

Post-MVP

## Goal

Move routing policies from offline evaluation to controlled execution with rollback.

## Scope

- Define policy states: draft, shadow, canary, active, and rolled back.
- Run shadow policies without changing execution choices.
- Route a bounded canary share to a new policy.
- Add quality, cost, latency, and failure guardrails.
- Roll back to the last known-good policy.

## Acceptance criteria

- A draft policy cannot route production work.
- A shadow policy produces comparable decision receipts.
- Canary guardrails stop a regression.
- Rollback restores the prior policy without changing trace history.

## Validation

Run a simulated release with injected quality, latency, and provider failures.
