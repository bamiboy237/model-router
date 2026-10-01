# Ticket 02: Build the rule-based router

## Stage

Beginning

## Goal

Select a worker from explicit task requirements and configurable capability priors.

## Scope

- Add task types: exploration, implementation, tests, debugging, refactoring, and architecture.
- Add model metadata: strengths, context limit, cost tier, latency target, and tool support.
- Reject models that violate hard task constraints.
- Select an eligible model with deterministic rules.
- Return a decision receipt with candidate scores and rule matches.

## Acceptance criteria

- The router rejects ineligible models.
- The receipt includes task requirements, eligible models, selected model, and rule matches.
- Configuration changes alter routing without code changes.
- Equal inputs produce equal decisions.

## Validation

Run table-driven routing tests.
