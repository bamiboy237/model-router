# Working in Stateful Model Router

## Goal

Build a state-aware router that assigns coding subtasks to heterogeneous models from measured evidence. The full system includes deterministic execution, offline learning, stateful context selection, safe policy rollout, and production evaluation.

## Build order

Follow the tickets in numeric order. Finish the deterministic execution and evaluation path before training a learned router. Finish offline evaluation before enabling online policy changes.

The stages are:

1. `00` through `03b`: establish contracts, workers, routing, verification, and escalation. Then build the trial lab in `src/trial_lab/`. The lab is a data factory: agents work on real tasks, and every trial becomes a training record. It also holds the benchmark and the fixed baselines.
2. `05`: build the orchestrator harness, an agent that delegates subtasks through the router.
3. `06` through `12`: add outcome prediction, policy utility, stateful context, replay, drift checks, safe rollout, and online evaluation.
4. `13` through `16`: add parallel task execution, local-execution decisions, adaptive specialization, and production control-plane interfaces.

## Core rules

- Treat model capability priors as configurable hypotheses, not facts.
- Record every execution with task features, selected context, model, cost, latency, result, verification evidence, and policy version.
- Use verifiable coding outcomes when available. Tests, type checks, and linters outrank model self-reported confidence.
- Keep worker context bounded. Store durable state outside prompts and send each worker only the context needed for its task.
- Keep routing policy separate from outcome prediction. The predictor estimates outcomes. The policy chooses an action.
- Preserve fixed baselines: always strongest, always cheapest, lowest latency, and rule-based routing.
- Keep benchmark task identity stable across runs. Store a new run rather than overwriting evidence.
- Keep offline policy evaluation reproducible before any online experiment.
- Make every decision explainable through a decision receipt with features, candidates, scores, constraints, and evidence.
- Use provider gateways and model APIs through adapters. Keep gateway, billing, and provider health concerns outside this project.

## Engineering standards

These rules keep the code small and the evidence trustworthy.

### Validate at boundaries

A boundary is where outside data enters: files in `config/`, `plans/`, and `tasks/`; rows read back from `runs/`; a `DelegationRequest`; provider responses; and output from host or sandbox commands. Parse each one into a `Contract` where it enters.

Inside the boundary, trust the types. A constructed `Contract` already meets its validators, so callers use it as is. When mypy needs a narrower type, reshape the type (a property that returns the narrowed value, or a union) instead of adding an `assert`.

Check the exit code of every command whose output the code uses. A failed command's output is error text, not data.

### One home for each rule

- Each invariant lives in one validator. Each shared format lives in one helper in `contracts.py`, for example the `provider:model_id` key, the git SHA pattern, micro-USD conversion, and canonical JSON hashing.
- Before writing a helper, search `model_router` for one. Logic that both packages need lives in `model_router`, because `trial_lab` imports it and not the reverse.
- A stored value derived from other stored values, such as `status`, `final_status`, or `StopReceipt` totals, is computed by one function. Validators confirm it; callers pass the result through.
- An ID is built once, by the code that owns it, and passed down.

### Grow surface with callers

Add a field, enum value, config key, export, or class in the same change as the code that reads it. When a ticket needs a piece before its caller exists, name the ticket in the piece's docstring. `__init__.py` exports what other packages import. Delete what nothing reads.

### Errors keep their traceback

Catch an exception only to turn it into a recorded outcome, as `classify_error` does. Every other exception propagates with its traceback. To add context, raise a new error `from` the original. Provider errors describe the provider, so they never count as model evidence.

### Records name their inputs

Every stored record names the versions that produced it: schema, policy, price table, and plan hash. A contract change that breaks reading existing rows in `runs/` bumps `SCHEMA_VERSION`. Runs already on disk stay as written.

### Docs move with code

A behavior change updates the ticket's Decisions or Limitations section in the same change, and the README when it shows the changed behavior. Comments explain why: a hidden constraint, an invariant, or a workaround, in the style of `contracts.py` and `workers/sandbox.py`.

## Trial lab package

`src/trial_lab/` runs trial plans and writes trial records. It shares this project's `pyproject.toml`.

- `trial_lab` imports `model_router`. `model_router` never imports `trial_lab`; it reads only the files the lab writes.
- `model_router` owns the contracts, including `TrialRecord`.
- Keep `trial_lab` under 2,000 lines of Python.
- Port ideas from the `legacy/support-v0` tag in `~/Desktop/simulate` (GitHub `bamiboy237/simulate`). Do not copy legacy files whole.

## Full-project completion

The project is complete when it can:

- execute a durable task graph across local and remote workers;
- select a model and minimal context packet from measured task state;
- verify results and escalate with bounded budgets;
- compare learned routing with fixed baselines on held-out tasks;
- replay traces and reproduce routing decisions;
- detect model-catalog changes and evaluation drift;
- roll out policies through shadow, canary, and rollback states;
- run independent subtasks in parallel with a task-level budget;
- choose local execution when delegation has negative expected value; and
- expose decision evidence, quality, cost, and latency to operators.

## Definition of done

For each ticket:

1. Implement the smallest complete change.
2. Do not add a test suite or test files.
3. Run `uv run ruff check .`, `uv run mypy src`, and `uv run python -m model_router.schemas --check`. When behavior needs checking, run a throwaway script and do not commit it.
4. Record assumptions and limitations in the ticket or README when they affect later work.

For every policy or predictor change:

1. Compare the change with fixed baselines.
2. Evaluate on held-out tasks.
3. Record the dataset, feature schema, policy version, and result.
4. Define rollback behavior before online use.

## Project boundaries

- Integrate with existing model gateways and provider APIs through adapters.
- Keep provider credentials and user content out of traces, fixtures, and reports.
- Use synthetic or consented task data for benchmark and production-like evaluation.
- Keep online learning disabled until offline evaluation is reproducible and policy rollback is tested.
- Keep broad general-agent planning outside this project. The orchestrator owns bounded coding task graphs.
