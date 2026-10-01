# Ticket 03a: Strip `simulate` to the trial-lab core

## Stage

Beginning. This ticket blocks tickets `03b` and `04`.

## Dependencies

None. This ticket touches only `~/Desktop/simulate`, so it can run before tickets `00` through `03`.

## Goal

Reduce `~/Desktop/simulate` to the smallest package model-router needs. The result is `trial_lab`: at most 350 lines of Python, no tests, and two runtime dependencies. Everything else moves to the git tag `legacy/support-v0`.

## How

An agent runs the `strip-simulate` skill at `~/Desktop/simulate/.agents/skills/strip-simulate/SKILL.md`. The skill holds the keep-list, the rules for porting each piece, and the checks. This ticket records why the cut is this deep.

## Why almost none of the 38,000 lines survive

The code builds a simulation product for support-refund agents. Not one line of it runs a coding task.

- **Isolation is support data.** Each sandbox is a set of PostgreSQL temporary tables for customers, orders, tickets, and policies (`src/app/domain/simulation/postgres.py:32-71`). The code has no filesystem or process isolation.
- **Measurements are fabricated.** `src/app/domain/reference/runner.py:288` adds 18 tokens per tool call. Line `:367` sets cost to tokens × 0.00005. The investigation gateway always returns `passed: True` (`src/app/domain/agent_runner/gateway.py:168`).
- **Real model usage is lossy.** Cache tokens are dropped. Cost is a best-effort provider field that is empty for unpriced models. Metrics pass through a span allowlist that drops unknown keys, and the code then parses them back out of the spans.
- **The code duplicates itself.** It has 6 cohort runners, 5 verdict enums, 9 hashing helpers, and 9 event models. The code path that actually runs does not use the experiment engine. Only tests call the engine.
- **The product scaffolding is the bulk.** FastAPI with 11 routers, 12 migrations, LangGraph, a Textual TUI, a 1,398-line CLI, and 15 runtime dependencies.
- **The docs and history are noisy.** There are 499 formulaic docstrings, about 150 KB of planning docs that no longer match the code, and about 12 MB of generated graph output in git.
- **The tests cover the platform.** The 24,600 lines of tests go with the platform.

## What survives

| Module | Why model-router needs it | Legacy source | Target size |
|---|---|---|---|
| `hashing.py` | One canonical content hash for plans and records | `canonical_json` in `experiment/contracts.py` | 20 lines |
| `plan.py` | A seeded N-arm schedule with deterministic trial IDs, which makes runs reproducible and resumable | `_build_support_suite_iteration_plan` and `IterationIdentity` in `experiment/contracts.py` | 90 lines |
| `execute.py` | A timeout and an error code per trial, where one failure does not stop the run | `execute_experiment` in `experiment/engine.py` | 60 lines |
| `models.py` | The only working provider code, with cache tokens added to usage | `build_pydantic_ai_model` and `_UsageTracker` in `adapters/pydantic_ai_agent.py` | 60 lines |
| `split.py` | A holdout split by family, which stops leakage in tickets `04` and `06` | `build_dataset_manifest` in `regression/dataset.py` | 30 lines |

If ticket `01` adopts pydantic-ai, `models.py` moves into model-router.

## Cut on purpose

- **Modal runner and Prime Agent harness.** The runner cannot exec, upload, or download. The harness records no usage. Port them from legacy only if the data from ticket `03b` shows that single-shot patches are not enough.
- **Trace ingestion (LangSmith, Braintrust, and evidence mapping).** Production traces belong to tickets `09` and `12`.
- **Evaluators and verdicts.** They are refund rules. Verifiers come from ticket `03`.
- **Immutable artifact references.** Ticket `03b` needs only one regular expression for a full commit SHA.
- **The whole test suite.**

## Acceptance criteria

- Every check in step 5 ("Prove it") of the skill passes.
- The tag `legacy/support-v0` points at the old `main`.
- The work is on the branch `strip/trial-lab-core`, and nothing has been pushed.
- The user's `.agents/` changes and untracked files are intact.

## Out of scope

The task corpus, workspaces, trial records, CLI, budgets, and resume belong to ticket `03b`.
