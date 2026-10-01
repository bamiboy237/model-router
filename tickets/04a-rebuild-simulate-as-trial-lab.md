# Ticket 04a: Break Simulate and rebuild it as the trial lab

## Stage

MVP (prerequisite for `04`)

## Goal

Turn `~/Desktop/simulate` into a small trial lab that runs `coding task × model × context packet × repetition` and emits immutable trial records for the router. Keep the few ideas that are sound. Delete the rest.

## Verdict on Simulate today

Simulate is about 41,000 lines of source and 24,600 lines of tests. It cannot run one coding trial. Measure it again before you start:

```bash
cd ~/Desktop/simulate && find src -name '*.py' | xargs wc -l | tail -1
grep -rln "Support\|refund" --include=*.py src/app/domain | wc -l
```

### Problems

1. **The support domain is welded into the core.** `RunMetrics` in `comparison/evaluators.py` requires `SupportOutcome`, `ReasonCode`, and `RouteIntent`. 43 domain files reference support or refund concepts. The engine imports `CompiledSupportScenario` inside a validator in `experiment/engine.py`. A coding task has none of these fields.
2. **The experiment design is fixed at two arms.** `ExperimentContract` supports one baseline and one candidate. Routing needs N models. `InterleavingPlan.repetitions` requires at least 3 runs, which blocks cheap smoke runs.
3. **The executor runs one iteration at a time.** `execute_experiment` loops sequentially. A matrix of 50 tasks × 4 models × 3 repetitions takes 600 serial calls.
4. **Budgets are declared but not enforced.** `ExecutionLimits` has `max_tokens` and `max_cost_usd`. The docstring admits the runner enforces only turns and duration. A paid benchmark without a cost ceiling is unsafe.
5. **Old and new code live side by side.** `comparison/` (v1) sits beside `experiment/` (v2). `reference/` sits beside `reference_workflows/`. `regression/`, `suite/`, and `failures/` overlap. `SupportSuiteExperimentContract` duplicates `ExperimentContract`. Every type is written as `A | B`.
6. **There are god objects.** `experiment/operator.py` is 1,504 lines and holds one class. `cli/main.py` has 1,398 lines, `cli/textual_simulate.py` has 1,547, and `agent_runner/bridge.py` has 1,183.
7. **Fixtures are code.** Each reference workflow fixture file is about 800 lines of Python. Task data belongs in files, not modules.
8. **The docs have more plan than product.** `BUILD_ROADMAP.md`, the two `PHASE8_*` plans, and `ARCHITECTURE.md` total about 2,000 lines. There is a `codemap.md` in every directory, and the `graphify-out/` artifacts are committed. Most of it describes phases that do not exist.
9. **The core depends on infrastructure.** Results need PostgreSQL, Alembic, an operator token, and a single operator lock. None of that helps a local, file-based benchmark.

### What to keep

Keep these ideas. Copy code only where it is small and has tests:

- Immutable, content-hashed identities for artifacts, prompts, and models (`ArtifactRef`, `PromptRef`, and `ModelRef` in `experiment/contracts.py`).
- A seeded, reproducible iteration plan.
- The runner callback protocol (`IterationRunner`) and one event per iteration.
- A stable error code for each failed iteration. One crash must not abort the cohort.
- Evaluators with versions that read normalized metrics, not provider internals.
- The `CloudRunner` protocol and `FakeRunner` in `runner/`, as the sandbox interface for coding tasks.
- The privacy allowlist idea for traces.

## Scope

### Break

- Freeze the current `main` with a tag, for example `pre-trial-lab`. Nothing is lost.
- Move the support product, investigation workflow, user simulator, Textual UI, retrieval, LangGraph workflow, trace ingestion, and PostgreSQL persistence out of the trial path. Delete them from the branch or leave them in a `legacy/` package that the new code never imports.
- Delete the per-directory `codemap.md` files, the committed `graphify-out/`, and the phase plans. Replace them with one README and one `AGENTS.md`.

### Rebuild

Build one new package, `trial_lab`, with these parts:

1. **`TaskFixture`**: data files, one per task. Each file holds a repository snapshot or reference, a task type, a prompt, a context packet, and a verifier command. Validate every file against a schema.
2. **`TrialMatrix`**: tasks × models × context variants × repetitions, with a seed. It takes N models. Repetitions start at 1.
3. **`Executor`**: runs trials concurrently with a concurrency limit. It enforces the token and cost ceilings before each call and rejects any ceiling it cannot enforce.
4. **`Sandbox`**: a disposable git worktree or container per trial. The `LocalSandbox` runs first, and a Modal sandbox comes later behind the same protocol.
5. **`Verifier`**: runs tests, type checks, and linters in the sandbox and records the exit code, the pass count, and the duration.
6. **`TrialRecord`**: append-only JSONL with schema version, task identity, model identity, context features, verifier results, tokens, cost, latency, and error code. The record must match the `ExecutionTrace` contract from ticket `00`.
7. **CLI**: `trial-lab run <matrix.yaml>` and `trial-lab report <records.jsonl>`. There are no other commands.

### Boundary

`trial_lab` does not import `model-router`, and `model-router` does not import `trial_lab`. They share only the `TrialRecord` schema.

## Acceptance criteria

- One matrix with 3 fixture coding tasks and 3 models, plus a fake provider, completes and writes 9 valid records.
- One real-provider run completes for at least one task per model, within a configured cost ceiling.
- A trial that crashes, times out, or exceeds its budget records an error code. The other trials in the matrix still complete.
- Re-running the same matrix and seed produces the same trial identities and appends new records.
- Adding a model or a task is a config or data change with no code change.
- The trial path imports nothing from support, investigation, simulator, workflow, or PostgreSQL code.
- The new package is under 3,000 lines of source.
- `model-router` ticket `04` reads the records without transforming them.

## Validation

- Unit tests for the matrix planner, budget enforcement, record schema, and verifier.
- An end-to-end test with the fake provider and `LocalSandbox` on the 3 fixture tasks.
- One check that fails the build if `trial_lab` imports a legacy module.
- `uv run ruff check`, `uv run mypy src/trial_lab`, and `uv run pytest tests/trial_lab -q`.

## Out of scope

- Learned routing, which is ticket `06`.
- Online experiments, which is ticket `12`.
- Any UI beyond the report command.
- Migrating old support experiment results.
