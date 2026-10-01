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

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script with a scripted `FunctionModel` against a fixture repository in Docker. Check the plain and Code Mode paths, the turn and time limits, error mapping, and sandbox isolation.

## Decisions

- **Provider library:** Pydantic AI. `openai` uses the Responses API, and `google` uses the Gemini API. Each provider reads its key from the host environment.
- **Worker loop:** the model has five file tools (`list_files`, `read_file`, `search`, `write_file`, `edit_file`) and a `run_command` tool. With `code_mode = true`, the file tools are only callable from inside Pydantic AI Harness `run_code` (Monty). `run_command` stays a normal tool.
- **Patch:** the model edits files directly. The worker computes the patch with `git diff` against `base_sha` inside the container. An empty diff is a valid empty patch.
- **Sandbox:** each attempt gets a fresh clone in a container. The container has no network and no environment variables from the host. It runs as the host user and has memory, CPU, and process limits. Every command, including `git diff`, runs inside the container, so a model cannot plant git hooks or config that the host would execute. Commands get a deadline inside the container, because killing the host-side `docker exec` does not stop them.
- **Limits:** each role sets `max_turns`, `max_total_tokens`, and `time_budget_s`. Exceeding turns or tokens records `budget_exceeded`. Exceeding time records `time_budget_exceeded`. Both count as `failed`.
- **Errors:** 429 is `rate_limited`, 5xx is `provider_unavailable`, and a 400 or 413 that mentions the context limit is `context_too_long`. Content filters are `refused`, malformed model output is `invalid_output`, and transport failures are `network_error`. Other 4xx errors, such as a bad key or an unknown model, are setup mistakes. They raise instead of being recorded.
- **Cost:** `config/prices.toml` stores USD per million tokens. Tokens times that price is exactly micro-USD, rounded up. Usage and cost are recorded even when the run fails, because the tokens were spent.

## Limitations

- Prices are the standard tier with short context. Long-context and batch rates are not modeled.
- Model choices per role are starting hypotheses. Ticket `06` replaces them with evidence.
- The default image is `python:3.12`. It has no `pytest`, and the sandbox has no network to install it. A task that needs tools must use an image that already contains them. Ticket `03b` adds per-task images.
- The time budget covers the agent loop, not sandbox setup.
- No live provider run has been recorded yet.
