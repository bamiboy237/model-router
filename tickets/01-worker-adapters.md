# Ticket 01: Add worker model adapters

## Stage

Beginning

## Goal

Run the same bounded task through multiple model providers behind one worker interface.

## Scope

- Run each attempt as a Pydantic AI agent loop in a fresh Docker sandbox.
- Configure exploration, coding, and reasoning as roles in `config/workers.toml`. A role sets the model, instructions, and limits. One adapter serves every role.
- Normalize provider responses into `TaskResult`.
- Capture input tokens, output tokens, cache usage, latency, and cost from a versioned price table.
- Map provider and loop failures to stable error codes.
- Accept a scripted `pydantic_ai` model in place of a provider for deterministic runs.

## Acceptance criteria

- A fixture task runs through the loop and returns a valid `TaskResult` with a patch.
- Provider-specific fields do not leak into the router contract.
- Adapter failures map to stable error categories.
- A model with no price fails before the first model call.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script with a scripted `FunctionModel` against a fixture repository in Docker. Check the plain and Code Mode paths, `run_checks()` and the reminders, the turn and time limits, error mapping, and sandbox isolation.

## Decisions

- **Provider library:** Pydantic AI. `openai` uses the Responses API, and `google` uses the Gemini API. Each provider reads its key from the host environment.
- **Worker loop (harness version 2):** the worker is Pydantic AI Harness `Coder`, run in the sandbox through `DockerWorkspace`. It brings the harness file tools (`read_file`, `write_file`, `edit_file` with batched replacements, `list_files`, `grep` with context lines), the `shell` tool, `RepoContext`, `SubAgents` (`delegate_task` to a fresh run of the same worker), clearing of old tool results, a 64,000-character output cap, argument repair, and prompt caching. Version 1 used six hand-written tools in `workers/tools.py`, which this replaces.
- **Done signal:** a `run_checks()` tool runs the task's visible verifiers exactly as listed and returns `PASS` or `FAIL` with each failing check's output tail. After a passing call, a reminder tells the model to reply unless the task needs more. Reminders at 50% and 80% of `max_turns` also steer it to finish. Reminders ride the uncached tail of the request, so they do not break prompt caching. In run `smoke-2`, the version 1 worker took 38 turns for a one-line fix and kept working after its tests passed.
- **Task message:** a short ordered workflow: read with batched lookups, make the smallest change, call `run_checks()`, stop when it passes. It rules out git history, tool-version checks, and benchmarks unless the task asks, which took about 15 of the 38 turns in `smoke-2`.
- **Code Mode:** off by default and set per plan arm (`code_mode = true`), not per role. When on, only `read_file`, `list_files`, and `grep` are callable inside `run_code` (Monty), so edits, checks, and commands stay visible as separate steps. In `smoke-2` every `run_code` call wrapped one tool, and Pydantic's own `Coder` does not use Code Mode, so the default waits for the A/B plan in ticket `03b`.
- **Harness version:** `HARNESS_VERSION` in `workers/worker.py` is recorded in every trial. Bump it with any change to tools, prompt, or reminders, and with any `pydantic-ai-harness` upgrade. The package is pinned to `0.52.0`.
- **Thinking:** set on the agent, not the run, so delegated runs inherit it.
- **Retries:** `run_worker` takes an optional `note`. Ticket `03` uses it to tell a retry or escalation what failed before.
- **Patch:** the model edits files directly. The worker computes the patch with `git diff` against `base_sha` inside the container. An empty diff is a valid empty patch.
- **Sandbox:** each attempt gets a fresh clone in a container. The container has no network and no environment variables from the host. It runs as the host user and has memory, CPU, and process limits. Every command, including `git diff`, runs inside the container, so a model cannot plant git hooks or config that the host would execute. Commands get a deadline inside the container, because killing the host-side `docker exec` does not stop them.
- **Limits:** each role sets `max_turns`, `time_budget_s`, and at least one of `max_total_tokens` and `max_cost_usd`. The cost cap is priced with the price table after each response. Exceeding turns, tokens, or cost records `budget_exceeded`. Exceeding time records `time_budget_exceeded`. Both count as `failed`.
- **Errors:** 429 is `rate_limited`, 5xx is `provider_unavailable`, and a 400 or 413 that mentions the context limit is `context_too_long`. Content filters are `refused`, malformed model output is `invalid_output`, and transport failures are `network_error`. Other 4xx errors, such as a bad key or an unknown model, are setup mistakes. They raise instead of being recorded.
- **Cost:** `config/prices.toml` stores USD per million tokens. Tokens times that price is exactly micro-USD, rounded up. Usage and cost are recorded even when the run fails, because the tokens were spent.

## Limitations

- Prices are the standard tier with short context. Long-context and batch rates are not modeled.
- Roles do not choose models. The router picks the model for each job (ticket `02`).
- The default image is `python:3.12`. It has no `pytest`, and the sandbox has no network to install it. A task that needs tools must use an image that already contains them. Ticket `03b` adds per-task images.
- The time budget covers the agent loop, not sandbox setup.
- Delegated runs share the trial's usage, so their tokens and cost are recorded and `max_turns` counts across the whole tree. Their messages are not in the parent transcript; only the delegated result is.
- The cost cap is checked between the parent run's steps. One long delegation can take a trial past `max_cost_usd` before the next check.
- `run_checks()` runs only the visible verifiers. The grader adds hidden tests, so a pass is the visible bar, not the trial's result.
- The sandbox images have no `rg`, so `grep` and `list_files` use the harness's POSIX `git`/`grep`/`find` fallback.
- `shell` keeps job files in `.pydantic-ai-harness/` in the checkout. The harness writes a `.gitignore` of `*` there, so they stay out of the patch.
- Harness version 2 has been checked with a scripted model against a local checkout, not yet in Docker or live.
- Live runs have been checked by hand only (`gemini-3.8-flash`, `gpt-5.6-sol`). No trace from them is stored.
