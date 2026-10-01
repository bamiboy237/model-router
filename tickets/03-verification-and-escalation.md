# Ticket 03: Verify work and escalate failures

## Stage

Beginning

## Goal

Use external evidence to accept, retry, or escalate worker results, and collect review feedback for later learning.

## Scope

- Run every check in the task's plan on a fresh checkout with only the patch applied.
- Fail a patch that does not apply or that changes a protected path.
- Retry a failed model with a note on what failed, then escalate to a stronger model.
- Retry provider errors on the same model after a backoff.
- Enforce attempt, cost, and time budgets, and give every stop a receipt.
- Record feedback from humans and the orchestrator as append-only events, and tally it per model and tag.
- Store traces without task text, patches, or repo locations.

## Acceptance criteria

- A passing verifier accepts a result.
- A missing required check gives `uncertain`, never `success`.
- A failing verifier triggers escalation when a stronger worker is available.
- The system stops when the escalation budget is exhausted.
- The trace reports cumulative cost and latency across attempts.
- Feedback cannot turn a failed required check into a success.
- A stored trace holds no instruction text, patch text, or repo path.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script with scripted `FunctionModel` workers against a fixture repository in Docker. Cover acceptance, retry then escalation, a protected-file edit, a provider error, a task with no checks, a cost stop, trace content, and the feedback tally.

## Decisions

- **Who checks.** Our code checks, not the worker. `verify()` clones `base_sha` into a new container, applies the patch, and runs each verifier. The worker may run checks too, but its own report is not evidence.
- **Router gates.** Every verification adds two required gates: `router.patch_applies` and `router.protected_paths`. Either one can fail an attempt. Passing them is not evidence that the task is done, so a task with no required verifiers ends `uncertain`.
- **Full plan.** `verification_status(checks, required)` judges results against the task's required verifier names. A required check that is missing, timed out, or could not run gives `uncertain`.
- **Check reasons.** A failing check is `assertion_failed`, `patch_conflict`, or `protected_path`. An inconclusive check is `timeout`, or `unavailable` for exit codes 126 and 127.
- **Protected paths.** Each task may list glob patterns. A patch that changes a matching path fails. Nothing is protected unless the task lists it. Renames count on both sides.
- **Retry and escalation.**
  - A failed attempt gets a retry on the same model, with the failing checks and the end of their output in the prompt. Each model gets `tries_per_model` (3) attempts.
  - Then the cheapest untried model with a higher success estimate for the task's tags takes over, with the same note. If none exists, the run stops with `no_stronger_model`.
  - An `uncertain` result from checks stops the run with `unverified`, because a stronger model cannot fix missing evidence.
- **Provider errors.** Rate limits, outages, and network errors retry the same model after 10 s, doubling each time, up to 2 retries in a row. They do not use up the model's tries or `max_attempts`, but they count toward cost and time.
- **Budgets.**
  - The defaults in `config/router.toml` are 6 attempts, $5, and 60 minutes of machine time. The orchestrator may lower them per task, but not raise them.
  - Before each attempt, its expected cost must fit in the remaining budget.
  - Human review happens outside `run_task`, so review time never counts.
- **Receipts.** Each attempt carries the router's receipt, with a rationale for the retry or escalation. Each trace ends with a `StopReceipt`. It records the reason, a detail, the attempt count, the total cost, and the active time.
- **Content-free traces.**
  - `TaskSpec` and `TaskResult` hold user content and live only in memory.
  - The trace stores `TaskSummary`, which has hashes of the instruction and repo, and `ResultSummary`, which has a patch hash and size. Provider error messages are not stored.
  - `run_task` returns the patches beside the trace, keyed by attempt id.
- **Feedback.**
  - `report_outcome()` records a verdict (`success`, `partial`, `failed`), an optional 1–5 rating, an optional aspect (`visual`, `logic`, `scope`, `style`, `other`), and the source (`human`, `orchestrator`). The event is tied to an attempt and its patch hash. Events hold no free text.
  - Events are append-only JSON lines. The latest event per attempt and source wins.
  - A rejection never acts on its own. The orchestrator decides whether to retry, escalate, or stop.
- **Tally.**
  - `tally()` gives each attempt one vote. In order of precedence:
    1. Failed required checks count as one failure.
    2. Otherwise, the latest human verdict counts at weight 1.
    3. Otherwise, the latest orchestrator verdict counts at weight 0.5.
    4. Otherwise, passing checks count as one success.
  - `partial` counts as half a success. Provider errors cast no vote.
  - The estimate blends votes with the configured prior, worth 10 attempts.
- **Schemas.** `schemas/feedback_event.v1.json` is checked in next to the trial record schema. Schema version 1 is not frozen until ticket `03b` writes data.

## Limitations

- Tally results are reported, not applied. Turning them into new priors and a new `policy_version` belongs to ticket `06`, after offline evaluation.
- Feedback is selected data. Only routed models get reviewed, and users who review differ from users who do not.
- Only command checks exist. Browser checks can run as commands with kind `browser`. Screenshot references and model judges wait for frontend fixtures in tickets `03b` and `04`.
- Only listed paths are protected. A patch can still weaken checks through files the task does not list, such as test configuration.
- The time budget is checked between attempts. One attempt can run past it, up to the role's own time limit.
- The cost budget uses expected cost. Actual cost can exceed it by up to one attempt.
- Setup errors, such as a failed clone or an unknown model, raise and leave no trace.
- Workers return only patches. The final text answer from `explore`, `review`, and `design` tasks is not captured yet.
- Context paths and verifier commands are stored as given. They come from the caller, not from user prompts.
