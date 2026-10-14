# Ticket 03b: Build the trial lab

## Stage

Beginning. Milestones 1 and 2 are done. This ticket blocks ticket `05`. It absorbs the old ticket `04` (benchmark and baselines).

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

An arm is `(model, context_strategy, thinking)`, as defined in `trial_lab.plan.Arm`. `thinking` is the reasoning effort (`minimal` to `xhigh`) or unset for the model's default. The only context strategy is `task_files`: the worker is pointed at the files the task lists.

A plan file in `plans/` declares the task selector (`tasks`, `families`, or neither for every task), the arms, the repetitions, the seed, `assignment`, the budget (`max_usd`), the concurrency limit, and the price table version (`prices`). `PlanFile.resolve` turns it into a `Plan`, and `build_trials` turns that into trials. The plan hash covers the resolved task IDs, arms, repetitions, seed, and assignment, but not the budget or concurrency, so raising the budget does not change trial IDs.

- Each trial is one attempt by one arm on one task, run with `model_router`'s worker and `verify()`. The lab does not retry or escalate. Retries are a routing decision, not part of the data.
- Each trial appends one JSONL row built with `model_router.trial_records(trace, lab)` from a single-attempt trace. The attempt's decision has policy `lab.all_arms`; its task features come from the router.
- `lab.router_receipt` holds the rule-based router's receipt for the task: the model it would have picked. `lab.arm_id` and `lab.thinking` name the arm.
- Worker transcripts, patches, verifier notes, and worker errors go in `runs/<run_id>/artifacts/<trial_id>/`, not in the row.
- A provider error (rate limit, outage, network) says nothing about the model. The trial goes to `errors.jsonl`, not `trials.jsonl`, and stays pending. Three in a row stop the run.
- A setup error, such as a rejected API key or a Docker failure, stops the run. In-flight trials finish first.

## Store, resume, and budget

```text
runs/<run_id>/
	plan.toml        the plan file as given at the start
	trials.jsonl     append-only, one row per finished trial
	errors.jsonl     provider errors; their cost counts toward the budget
	artifacts/
```

- `lab run <plan>` starts a new run, `<plan_id>-<UTC time>`. `lab run <plan> --run-id <id>` resumes that run. It refuses if the resolved plan hash differs from the stored plan's, and skips every `trial_id` already in `trials.jsonl`. A partial last row from a killed run is dropped.
- A new run of the same plan has the same trial IDs and a new `run_id`, so task identity stays stable and no evidence is overwritten.
- Up to `concurrency` trials run at once. Each worker keeps its role's time budget, and each verifier its own timeout.
- Before it starts a trial, the runner reserves the trial's expected cost: the larger of the router's usage guess and the highest cost that arm has recorded. It starts no trial whose reservation would take spend, including other reservations, past `max_usd`. When over, it waits for in-flight trials to free their reservations before it stops.
- Every `lab run` runs admission on the plan's tasks first. A plan with an unpriced model, or a price table version that differs from `config/prices.toml`, fails before any model call.
- The first live budget is $25.

## Command-line interface

- `lab tasks check`: validates task files and runs admission.
- `lab plan <plan.toml>`: prints the trial count and the estimated cost.
- `lab run <plan.toml> [--run-id <id>]`: starts a run, or resumes the run with that id.
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

## Milestone 2 results

Checked with throwaway scripts, not committed:

- Scripted plan of 10 tasks × 3 arms (reference, bad, and empty patches) × 3 repetitions, concurrency 4. Killed with `SIGKILL` after 30 rows, with a partial row appended by hand. The resume dropped the partial row and recorded the other 60. All 90 trial IDs are unique and match the plan. Every reference trial passed; every bad and empty trial failed.
- Building the same plan twice gives identical trials; another seed gives other IDs and order.
- An unpriced model and a stale price table version both fail in `prepare`, before any model call.
- A $0.26 budget with about $0.25 reserved per trial stopped after 6 trials, with $0.025 recorded.

Live smoke (`plans/smoke.toml`, run `smoke-1`): `typedkey-kwargs` with Gemini 3.8 Flash, thinking high.

- Failed with `budget_exceeded`: 1,522,518 total tokens against the coding role's 1,500,000, after 40 requests, 385 s, and $0.41. The 39th tool call made a correct-looking edit. The limit counts every request's full input, cached tokens included, so long sessions reach it even when cost is low.
- Tokens match. The record's usage equals the sum of all 40 provider responses. The transcript holds only 39, because the response that crossed the limit is billed and counted but never joins the message history. On those 39, the price table's cost equals pydantic-ai's price data to the micro-dollar.
- Gemini reports thinking tokens inside `output_tokens` (38,755 of 41,416 here), so they are billed at the output rate.
- The worker ran `git log`, `git reflog`, and `git tag` to look for the fix. The snapshot showed one commit.

The coding role now caps cost, not tokens: `max_cost_usd = 5` in `config/workers.toml`, priced with the price table after each response. Run `smoke-2` with the cap passed every check: 38 requests, 1,578,185 input tokens (1,354,129 cached), 45,249 output tokens, $0.44, and 417 s. Its recorded tokens equal the transcript's sum.

Known limits:

- The budget reservation is an estimate. One trial can cost more than its reservation, so a run can end slightly over `max_usd`. The role's `max_cost_usd`, or its token limit when it has no cost cap, bounds how far.
- `SIGKILL` on the runner leaves its sandbox containers running. They carry the label `model-router.sandbox=1` and exit after `SandboxConfig.lifetime_s` (2 hours).
- `lab run` does not read `.env`. Load keys into the environment first.

## Notes

- Hidden test patches and fixture tests are task data, not a project test suite.
- Bug-injection task generation waits for milestone 4, after the runner works.
