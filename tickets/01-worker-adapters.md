# Ticket 01: Add worker model adapters

## Stage

Beginning

## Goal

Run the same task through multiple model providers behind one worker interface.

## Scope

- Run each attempt as a Pydantic AI agent loop in a fresh Docker sandbox.
- Configure exploration, coding, and reasoning as roles in `config/workers.toml`. A role sets instructions. The router selects the model. One adapter serves every role.
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

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script with a scripted `FunctionModel` against a fixture repository in Docker. Check the plain and Code Mode paths, `run_checks()` and its reminder, delegation beyond 50 requests, usage accounting, error mapping, and sandbox isolation.

Version 3 regression check: both tool modes omit `delegate_task`, reject an attempted delegation, and stop after exactly three model requests under a three-request limit. Both modes also read and edit a fixture, call `run_checks()`, and return a patch that passes verification in a fresh container. A throwaway script checked these paths without adding test files.

Version 4 regression check: both tool modes completed 53 parent requests and 53 delegated requests in Docker, then returned a patch that passed verification in a fresh container. Delegated usage contributed to the recorded cost. Scripted pricing put cost above the old worker cap without stopping either run.

## Decisions

- **Provider library:** Pydantic AI. `openai` uses the Responses API, `google` uses the Gemini API, and `meta` uses the OpenAI-compatible Responses API at `https://api.meta.ai/v1`. Meta reads `MODEL_API_KEY`. Its profile enables thinking, encrypted reasoning replay, commentary phases, and stateless requests. See [Meta integration notes](../docs/meta-model-api.md) for official sources and the smoke command.
- **DeepSeek V4.1 Flash:** `deepseek` uses the Responses adapter with the installed `DeepSeekProvider`, `DEEPSEEK_API_KEY`, and API ID `deepseek-flash`. Its profile supplies reasoning support and the context window because the SDK recognizes only the older V4 model names. The provider handles raw reasoning replay and tool-call ordering. The live smoke passed hidden tests with four requests. See [DeepSeek integration notes](../docs/deepseek-model-api.md) for sources, validation, and price-accounting limits.
- **Worker loop (harness version 4):** the worker is Pydantic AI Harness `Coder`, run in the sandbox through `DockerWorkspace`. It brings the harness file tools (`read_file`, `write_file`, `edit_file` with batched replacements, `list_files`, `grep` with context lines), the `shell` tool, `RepoContext`, `SubAgents`, clearing of old tool results, a 64,000-character output cap, argument repair, and prompt caching. Version 1 used six hand-written tools in `workers/tools.py`, which this replaces.
- **Delegation:** `Coder` enables `delegate_task` in both direct and Code Mode runs. Delegates share the parent's usage. `_UnlimitedRequests` removes Pydantic AI's default 50-request cap on every run, including delegates. Thinking settings and capabilities are bound to the agent so delegates inherit them.
- **Done signal:** a `run_checks()` tool runs the task's visible verifiers exactly as listed and returns `PASS` or `FAIL` with each failing check's output tail. After a passing call, a reminder tells the model to reply unless the task needs more. The reminder does not stop execution. Version 4 has no turn-budget reminders.
- **Task message:** a short ordered workflow: read with batched lookups, make the smallest change, call `run_checks()`, stop when it passes. It rules out git history, tool-version checks, and benchmarks unless the task asks, which took about 15 of the 38 turns in `smoke-2`.
- **Code Mode:** off by default and set per plan arm (`code_mode = true`), not per role. When on, only `read_file`, `list_files`, and `grep` are callable inside `run_code` (Monty), so edits, checks, and commands stay visible as separate steps. In `smoke-2` every `run_code` call wrapped one tool, and Pydantic's own `Coder` does not use Code Mode, so the default waits for the A/B plan in ticket `03b`.
- **Harness version:** `HARNESS_VERSION` in `workers/worker.py` is recorded in every trial. Bump it with any change to tools, prompt, or reminders, and with any `pydantic-ai-harness` upgrade. The package is pinned to `0.52.0`.
- **Thinking:** set on the agent's `model_settings`.
- **Retries:** `run_worker` takes an optional `note`. Ticket `03` uses it to tell a retry or escalation what failed before.
- **Patch:** the model edits files directly. The worker computes the patch with `git diff` against `base_sha` inside the container. An empty diff is a valid empty patch.
- **Sandbox:** each attempt gets a fresh clone in a container. The container has no network and no environment variables from the host. It runs as the host user and has memory, CPU, and process limits. Every command, including `git diff`, runs inside the container, so a model cannot plant git hooks or config that the host would execute. Commands get a deadline inside the container, because killing the host-side `docker exec` does not stop them.
- **Limits:** at the user's request, version 4 removes worker request, token, cost, and wall-time caps. Roles contain only `name` and `instructions`. Old role limit keys are rejected and must be removed from custom configuration. Docker resources, container lifetime, command deadlines, verifier timeouts, and the harness's default delegation depth remain. The router's retry budget is separate and is checked between attempts.
- **Errors:** 429 is `rate_limited`, 5xx is `provider_unavailable`, and a 400 or 413 that mentions the context limit is `context_too_long`. Content filters are `refused`, malformed model output is `invalid_output`, and transport failures are `network_error`. Other 4xx errors, such as a bad key or an unknown model, are setup mistakes. They raise instead of being recorded.
- **Cost:** `config/prices.toml` stores USD per million tokens. Tokens times that price is exactly micro-USD, rounded up. Usage and cost are recorded even when the run fails, because the tokens were spent.

## Limitations

- Prices are the standard tier with short context. Long-context and batch rates are not modeled.
- Roles do not choose models. The router picks the model for each job (ticket `02`).
- The default image is `python:3.12`. It has no `pytest`, and the sandbox has no network to install it. A task that needs tools must use an image that already contains them. Ticket `03b` adds per-task images.
- A worker can continue until it finishes, fails, or its caller cancels it. There is no worker spend cap.
- Delegated messages are not included in the parent transcript, although their usage and cost are counted.
- `run_checks()` runs only the visible verifiers. The grader adds hidden tests, so a pass is the visible bar, not the trial's result.
- The sandbox images have no `rg`, so `grep` and `list_files` use the harness's POSIX `git`/`grep`/`find` fallback.
- `shell` keeps job files in `.pydantic-ai-harness/` in the checkout. The harness writes a `.gitignore` of `*` there, so they stay out of the patch.
- Harness version 2 passed a live Docker smoke run and three A/B trials. These records stay under `runs/review-pr1-*` with their original harness version.
