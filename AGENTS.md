# Working in Stateful Model Router

## Goal

Build a state-aware router that assigns coding subtasks to heterogeneous models from measured evidence. The full system includes deterministic execution, offline learning, stateful context selection, safe policy rollout, and production evaluation.

## Build order

Follow the tickets in numeric order. Finish the deterministic execution and evaluation path before training a learned router. Finish offline evaluation before enabling online policy changes.

The stages are:

1. `00` through `03b`: establish contracts, workers, routing, verification, and escalation. Then build the trial lab in `src/trial_lab/` on the core stripped from `simulate`.
2. `04` through `05`: build the benchmark and complete the rule-based MVP orchestrator.
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
