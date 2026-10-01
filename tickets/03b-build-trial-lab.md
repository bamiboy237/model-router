# Ticket 03b: Build the trial lab on the stripped core

## Stage

Beginning. This ticket blocks ticket `04`.

## Dependencies

- Ticket `03a` has stripped `~/Desktop/simulate` to `trial_lab`.
- Tickets `00`, `01`, and `03` provide `TaskSpec`, `ContextPacket`, `TaskResult`, `TrialRecord`, worker adapters, and verifiers.

## Goal

Run a matrix of coding task × arm × repetition in isolated workspaces. Verify each result, and append one immutable trial record per trial. model-router trains and evaluates only from those records.

## Boundary

```text
model-router (library)   contracts, worker adapters, verifiers, routing policies
simulate (trial_lab)     task corpus, workspaces, trial plans, execution, trial store, reports
```

- The lab imports model-router as a library, so training and routing share one implementation of workers and verifiers.
- model-router reads only the files the lab writes. It never imports the lab.
- model-router owns the `TrialRecord` schema.

## Task corpus

Each task is a directory:

```text
tasks/<family>/<task_id>/
	task.yaml         prompt, task_type, repo, base_sha, features, verifiers, limits
	reference.patch   known-good solution
	bad.patch         optional known-bad solution
```

- `repo` is a local path or a git URL. `base_sha` must be a full 40- or 64-character commit hash.
- `family` is the unit for `split_by_family`. Tasks from one repository or one generator share a family.
- `features` holds the task features that ticket `06` trains on: task type, file count, context tokens, language, and verifiability.

Before a task can enter a plan, it must pass admission:

1. The reference patch passes every required verifier.
2. The empty patch fails at least one required verifier.
3. The bad patch, if present, fails at least one required verifier.

Admission stops a broken verifier from turning into a wrong training label.

## Arms and plans

An arm is `(model, context_strategy)`, as defined in `trial_lab.plan.Arm`. The context strategy selects how the lab builds the `ContextPacket`, for example `full_files`, `relevant_files`, or `summary`.

A `plan.yaml` file declares the task selector, the arms, the repetitions, the seed, the budget (`max_usd` and `max_trials`), the concurrency limit, and the price table version. `build_trials` turns it into trials.

## Workspace

The workspace protocol has five operations: `prepare(task)`, `apply(patch)`, `run(command, timeout)`, `diff()`, and `destroy()`.

- The default backend is a local container with a clean checkout at `base_sha` and no network.
- Verifier commands run without provider credentials in their environment.
- A plain subprocess backend is available for synthetic tasks, and only behind an explicit `--unsafe-local` flag. Verifiers execute code the model wrote.

## Trial record

Each trial appends one JSONL row that validates against `TrialRecord`:

- `schema_version`, `trial_id`, `plan_hash`, `run_id`, and `started_at`.
- `task_id`, `task_family`, `task_features`, `arm`, and `repetition`.
- `usage`: input, output, cache read, and cache write tokens from the provider response.
- `cost_micro_usd`, computed from a versioned price table. If an arm uses a model with no price, the plan fails before the first model call.
- `latency`: model call, verification, and total, in milliseconds.
- `checks`: name, version, required, passed, exit code, duration, and output hash for each verifier.
- `status`: `success`, `failed`, or `uncertain`, plus an `error_code`. Rate limits, provider outages, and network errors are `uncertain`, because they say nothing about the model's ability. Context overflows, refusals, and time-budget overruns are `failed`.
- `lab`: `trial_id`, `run_id`, `plan_hash`, `repetition`, `task_family`, and the artifacts path.

Build each row with `model_router.trial_records(trace, lab)` from a single-attempt trace, not by hand.
- `patch_hash` and the relative path to the trial's artifacts.

Raw prompts, responses, patches, and verifier logs go in `runs/<run_id>/artifacts/<trial_id>/`, not in the row.

## Store, resume, and budget

```text
runs/<run_id>/
	plan.yaml
	trials.jsonl     append-only
	artifacts/
```

- To resume a run, execute the plan again. The runner skips every `trial_id` already in `trials.jsonl`.
- `run_trials` gains a concurrency limit. Each trial keeps its own timeout.
- The runner estimates cost before it starts and tracks recorded spend as trials finish. It stops scheduling trials before spend exceeds `max_usd`.

## Command-line interface

- `lab tasks check`: validates task files and runs admission.
- `lab plan <plan.yaml>`: prints the trial count and the estimated cost.
- `lab run <plan.yaml>`: executes or resumes a plan.
- `lab report <run_id>`: prints success, cost, and latency per arm and task type, with `insufficient_evidence` for cells below the minimum sample size.
- `lab export <run_id>... --split`: writes the training and holdout datasets for tickets `04` and `06`.

## Milestones

1. **Tasks and admission.** Add the task schema, admission, and 10 seed tasks. Cover at least four task types across at least three families.
2. **Execute.** Add the container workspace, the single-shot patch worker (through model-router adapters), verifiers, trial records, the budget stop, concurrency, and resume.
3. **Report and export.** Add the per-arm report and the family-grouped export.
4. **Agentic and remote (after the MVP).** Port the Modal backend and the Prime Agent harness from `legacy/support-v0`, or write a small tool loop. Decide from the milestone 3 data.

## Acceptance criteria

- A plan of 10 tasks × 3 arms × 3 repetitions runs end to end with a scripted worker and writes 90 valid trial records.
- The same plan and seed produce identical trial IDs and order.
- A run killed partway finishes on restart without repeating any recorded trial.
- Admission rejects a task whose reference patch fails, and a task whose empty patch passes.
- A plan with an unpriced model fails before the first model call.
- The run stops before its recorded spend exceeds `max_usd`.
- Verifier commands run with no network and no provider credentials.
- Every token, cost, and latency value in a trial record comes from a provider response, the price table, or a clock.
- `trial_lab` stays under 2,000 lines of Python.

## Validation

- Run the 90-trial scripted plan, kill it partway, and resume it.
- Run `lab tasks check` against the seed corpus, plus one task with a broken verifier.
- Run one live smoke plan of 2 tasks × 2 models × 1 repetition. Compare the recorded token counts with the usage in the provider responses.

## Open questions

- Task source: write the first 10 tasks by hand, or adapt public tasks in the style of SWE-bench Lite? Writing them by hand first keeps admission and feature extraction honest.
- Name: keep `simulate`, or rename the repository to match its new purpose?
