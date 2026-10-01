# Ticket 07: Add the learned routing policy

## Stage

Post-MVP

## Goal

Choose a model from predicted outcomes and explicit quality, cost, latency, and risk preferences.

## Scope

- Define a utility function over predicted quality, cost, latency, escalation risk, and context transfer.
- Apply hard constraints before utility ranking.
- Support policy profiles for quality-first, cost-first, and latency-first routing.
- Record the policy version and score breakdown in each decision receipt.
- Compare learned policy choices with fixed baselines.

## Acceptance criteria

- Hard constraints exclude invalid candidates.
- Policy profiles produce different choices on controlled fixtures.
- Decision receipts show candidate predictions, utility terms, and the selected action.
- The learned policy does not use future execution results.

## Validation

Run table-driven policy tests and held-out benchmark comparisons.
