# Ticket 03b: Build the trial lab

## Stage

Beginning. This ticket blocks ticket `05`. It absorbs the old ticket `04` (benchmark and baselines).

## Purpose

The lab is a data factory. Agents work on real tasks from real codebases in Docker sandboxes. Every trial leaves a trial record: the model, the context, token usage, cost, latency, check results, and the router's receipt. Tickets `06` and later train the real routing model from these records.

The lab runs in two stages:

1. **Stage 1, the first round.** Every model in a plan tries every task, in shuffled order. The rule-based router also writes a receipt of the model it would have picked. The data has no bias toward the models the rules favor.
2. **Stage 2, the training loop.** A model trained on the stage 1 data picks models in the lab. The lab collects more data, and the model is trained again. Tickets `06` and `07` build this. This ticket only leaves room for it: plans have an `assignment` setting, and stage 1 uses `all_arms`.

## Boundary

```text
src/model_router   contracts, worker adapters, verifiers, routing policies
src/trial_lab      task corpus, snapshots, admission, plans, runs, trial store, reports
```

- Both packages live in this repository and share one `pyproject.toml`.
- `trial_lab` imports `model_router`, so the lab uses the same worker and verifier as the router.
- `model_router` reads only the files the lab writes. It never imports the lab.
- `model_router` owns the `TrialRecord` schema.

## Task corpus

Each task is a directory under `tasks/`:

```text
tasks/<family>/<task_id>/
	task.toml            id, family, kind, domain, image, source, instruction, files, verifiers
	setup.patch          optional; turns the source into the task's starting point, e.g. a bug
	reference.patch      known-good solution
	bad.patch            optional plausible wrong solution
	hidden_tests.patch   optional; applied only when checking
tasks/_repos/<name>/     fixture projects written for the lab
```

- **Sources.** A task comes from a pinned upstream commit (`upstream.url`, `upstream.sha`) or from a fixture project in `tasks/_repos/`.
- **First projects.** `cachetools` v7.2.0 is a pure-Python library. Flask 3.1.3's `flaskr` tutorial app is a small web service. `shopfront` is a small React and TypeScript app written for the lab, because no small, well-tested open-source frontend fit.
- **Snapshots.** The lab builds each task's repository as one commit with no history, from the source plus `setup.patch`. A worker cannot read the upstream fix, or the commit that injected a bug, from `git log`. The commit has fixed metadata, so the same files always give the same `base_sha`.
- **Hidden tests.** `hidden_tests.patch` is applied after the worker's patch, only in the verification sandbox. The worker never sees it. A worker patch that touches its paths fails the protected-paths gate.
- **Images.** Sandboxes have no network. `images/python` and `images/node` build `model-router/python:1` and `model-router/node:1` with every tool and dependency the tasks need. Each task names its image.
- **Families** are the unit for `split_by_family`. Tasks from one project share a family.
- **Difficulty** is not set by hand. Reports measure it from pass rates.

Before a task can enter a plan, it must pass admission:

1. The reference patch passes every required verifier.
2. The empty patch fails at least one required verifier.
3. The bad patch, if present, fails at least one required verifier.

Admission stops a broken verifier from turning into a wrong training label. It counts only task verifiers, not the router's gates: a bad patch that does not apply, or that changes protected paths, is rejected because it does not test the verifiers.

Conventions for authoring tasks:

- Name hidden test files `test_lab_hidden_*` (or `lab_hidden_*.test.tsx`), so they do not collide with tests a worker adds. A worker patch that touches a hidden test path fails.
- `test` tasks check the worker's tests with mutants. `hidden_tests.patch` adds `.lab/kill_mutants.sh` and `.lab/mutants/*.patch`. The `mutants` verifier applies each mutant, runs the worker's tests, and fails if any mutant survives. Protect the code under test, so the mutants still apply.
- Build patches from exact edits with `git diff`. Do not write diffs by hand.
- Every verifier that runs hidden tests sets `junit_path` (outside the checkout) and lists the hidden test files in `expect_tests`. An exit code of 0 is not enough: the report must show every listed file's tests ran and passed, or the check fails with `tests_not_run`. Admission rejects a task whose hidden test files are not listed.

### Grading defenses

A worker can try to pass the checks without doing the task. Two defenses apply to every task:

1. **Test setup files are protected.** `TEST_SETUP_PATHS` in `model_router.contracts` lists them: `conftest.py`, pytest and tox settings, `setup.cfg`, `pyproject.toml`, `sitecustomize.py`, `package.json`, Vite and Vitest config, and `tsconfig*.json`, in any directory. A patch that adds or changes one fails the protected-paths gate. The worker prompt lists them.
2. **Reports prove the hidden tests ran.** See `expect_tests` above.

Checked with cheat patches: a new `conftest.py` hook that marks failures as passed and a Vitest `exclude` are blocked by the gate. A test file that calls `os._exit(0)` passed before the report check and fails with it.

Known limits:

- Tasks cannot change `pyproject.toml` or `package.json`, so tasks that need a dependency or script change are out of scope.
- A worker that knows a hidden test file's name could write a fake report. Hidden test names are not shown to workers, but the `test_lab_hidden_*` convention is predictable.
- A test-writing worker can kill mutants with tests that compare the source text. Equivalent rewrites that the tests must not reject would catch this. Not built yet.

### Seed corpus

| Family | Task | Kind | Bad patch |
| --- | --- | --- | --- |
| `cachetools` | `typedkey-kwargs` | fix | adds key-name types instead of value types |
| `cachetools` | `setitem-resize-size` | fix | clamps `currsize` at zero |
| `cachetools` | `maxsize-setter` | build | sets the limit without evicting |
| `cachetools` | `keys-tests` | test | weak tests; all 5 mutants survive |
| `flaskr` | `delete-author-check` | fix | returns 404 instead of 403 |
| `flaskr` | `posts-json-api` | build | `created` not in ISO 8601 |
| `flaskr` | `user-queries-refactor` | refactor | adds helpers but keeps inline SQL |
| `shopfront` | `duplicate-cart-lines` | fix | merges lines only for display |
| `shopfront` | `category-filter` | build | hard-codes the category list |
| `shopfront` | `cart-tests` | test | weak tests; 6 of 7 mutants survive |

## Plans and trials

An arm is `(model, context_strategy)`, as defined in `trial_lab.plan.Arm`. A `plan.toml` file declares the task selector, the arms, the repetitions, the seed, `assignment`, the budget (`max_usd`), the concurrency limit, and the price table version. `build_trials` turns it into trials.

- Each trial is one attempt by one arm on one task, run with `model_router`'s worker and `verify()`. The lab does not retry or escalate. Retries are a routing decision, not part of the data.
- Each trial appends one JSONL row built with `model_router.trial_records(trace, lab)` from a single-attempt trace.
- The rule-based router's receipt for the task is stored with each trial.
- Raw prompts, responses, patches, and verifier logs go in `runs/<run_id>/artifacts/<trial_id>/`, not in the row.

## Store, resume, and budget

```text
runs/<run_id>/
	plan.toml
	trials.jsonl     append-only
	artifacts/
```

- To resume a run, execute the plan again. The runner skips every `trial_id` already in `trials.jsonl`.
- `run_trials` gains a concurrency limit. Each trial keeps its own timeout.
- The runner estimates cost before it starts and tracks recorded spend as trials finish. It stops scheduling trials before spend exceeds `max_usd`.
- The first live budget is $25. Until then, runs use scripted models only.

## Command-line interface

- `lab tasks check`: validates task files and runs admission.
- `lab plan <plan.toml>`: prints the trial count and the estimated cost.
- `lab run <plan.toml>`: executes or resumes a plan.
- `lab report <run_id>`: prints success, cost, and latency per arm, task kind, and family, with `insufficient_evidence` for cells below the minimum sample size. It also scores the fixed baselines on the run's data.
- `lab export <run_id>... --split`: writes the training and holdout datasets for ticket `06`.

## Milestones

1. **Tasks and admission.** Task schema, snapshots, hidden tests, sandbox images, admission, and 10 seed tasks. Cover at least four task kinds across the three projects.
2. **Stage 1 runs.** Plans, the runner, trial records with router receipts, the budget stop, concurrency, and resume.
3. **Reports, baselines, and export.** Per-arm reports, measured task difficulty, and the fixed baselines: always strongest, always cheapest, lowest latency, and the rule-based router. Every model ran every task, so each baseline is scored on the same data. Family-split export.
4. **Later.** Generated tasks from bug injection, 1–2 SWE-bench Lite tasks, stage 2 assignment, and remote backends.

## Acceptance criteria

- A plan of 10 tasks × 3 arms × 3 repetitions runs end to end with a scripted worker and writes 90 valid trial records.
- The same plan and seed produce identical trial IDs and order.
- A run killed partway finishes on restart without repeating any recorded trial.
- Admission rejects a task whose reference patch fails, and a task whose empty patch passes.
- A plan with an unpriced model fails before the first model call.
- The run stops before its recorded spend exceeds `max_usd`.
- Verifier commands run with no network and no provider credentials.
- Every token, cost, and latency value in a trial record comes from a provider response, the price table, or a clock.
- Re-running a plan keeps task identity and records a new run.
- Holdout tasks never reach routing configuration or training data.
- `trial_lab` stays under 2,000 lines of Python.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then:

- Run `lab tasks check` against the seed corpus, plus one task with a broken verifier.
- Run the 90-trial scripted plan, kill it partway, and resume it.
- Before the first live run, run one live smoke plan of 1 task × 1 model × 1 repetition, and compare the recorded token counts with the provider response.

## Notes

- Hidden test patches and fixture tests are task data, not a project test suite.
- Bug-injection task generation waits for milestone 4, after the runner works.
