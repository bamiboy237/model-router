# Ticket 00: Define the execution contracts

## Stage

Beginning

## Goal

Define the stable data contracts for tasks, context packets, worker results, decisions, verification, and execution traces.

## Scope

- Create typed schemas for `TaskSpec`, `ContextPacket`, `TaskResult`, `DecisionReceipt`, `VerificationResult`, `ExecutionTrace`, and `TrialRecord`.
- Export `TrialRecord` as a versioned JSON Schema. The trial lab in ticket `03b` writes rows that must validate against it.
- Include task type, context references, verifier configuration, selected model, token counts, cost, latency, policy version, and outcome.
- Define result statuses: `success`, `failed`, and `uncertain`.
- Define trace lineage for retries and escalations.

## Acceptance criteria

- Schemas serialize to JSON.
- Invalid or incomplete worker results fail validation.
- A trace represents a failed task followed by an escalation.
- A decision receipt explains why a candidate was selected or rejected.

## Validation

Run `ruff`, `mypy --strict`, and `python -m model_router.schemas --check`. By user decision, this ticket ships without a test suite.

## Decisions

- Cost is an integer count of millionths of a US dollar (`cost_micro_usd`), so sums stay exact.
- One `ExecutionTrace` per task holds every attempt. Each attempt names its parent and its cause: `initial`, `retry`, or `escalation`. An escalation must change the model.
- `TrialRecord` rows come from traces through `trial_records()`. Rows are never written by hand. Rows from `trial_lab` add a `lab` block.
- Status always follows the evidence, and validation rejects a status that contradicts it. A failed required check means `failed`. A missing or inconclusive check means `uncertain`.
- Error codes split by whether they say something about the model:
  - `uncertain`: `rate_limited`, `provider_unavailable`, and `network_error`. These describe the provider.
  - `failed`: `context_too_long`, `refused`, `time_budget_exceeded`, `invalid_output`, and `patch_apply_failed`. These describe the model's fit for the task.
  - Ticket `01` adapters map each provider's HTTP status and message to one code. A network-level timeout is `network_error`. A model that runs past the task's time budget is `time_budget_exceeded`.
- `schemas/trial_record.v1.json` is checked in. CI regenerates it and fails on drift.

## Limitations

- `.github/workflows/ci.yml` does nothing until `model-router` is its own git repository.
- Context strategy is recorded on the context packet, not scored as a decision candidate. Ticket `02` may add it to candidates.
