# Ticket 01: Add worker model adapters

## Stage

Beginning

## Goal

Run the same bounded task through multiple model providers behind one worker interface.

## Scope

- Define a worker adapter protocol.
- Add three configurable adapters for exploration, coding, and reasoning workers.
- Normalize provider responses into `TaskResult`.
- Capture input tokens, output tokens, latency, cost, and provider-reported cache usage when available.
- Support mocked responses for deterministic tests.

## Acceptance criteria

- A fixture task runs through each adapter.
- Each adapter returns a valid `TaskResult`.
- Provider-specific fields do not leak into the router contract.
- Adapter failures map to stable error categories.

## Validation

Run adapter contract tests with mocked provider responses.
