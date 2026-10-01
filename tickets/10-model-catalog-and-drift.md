# Ticket 10: Manage the model catalog and drift

## Stage

Post-MVP

## Goal

Keep model capabilities, prices, limits, and observed performance current.

## Scope

- Define a versioned model catalog with provider, context limit, tools, prices, latency targets, and capability tags.
- Validate catalog changes before routing uses them.
- Add scheduled benchmark evaluation for catalog entries.
- Detect data drift, quality regressions, price changes, and unavailable models.
- Mark stale predictions and route safely when evidence is missing.

## Acceptance criteria

- Catalog changes create a new version.
- Invalid limits and prices fail validation.
- Drift reports identify the affected task cohorts and model versions.
- A stale or unavailable model cannot be selected as the only candidate.

## Validation

Run catalog schema tests, drift fixtures, and unavailable-model routing tests.
