# Muse Spark in the trial lab

Official references checked on 2026-10-14:

- [Models](https://dev.meta.ai/docs/models): `muse-spark-1.3`, with a 1,048,576-token context window.
- [Responses API](https://dev.meta.ai/docs/protocols/responses): OpenAI-compatible requests, streamed tools, encrypted reasoning replay, and commentary phases.
- [Reasoning](https://dev.meta.ai/docs/reasoning): the smoke arm uses `medium` effort. Disabling reasoning is unsupported.
- [Pricing](https://dev.meta.ai/docs/pricing-rate-limits): standard-mode rates per million tokens are $1.25 input, $0.15 cached input, and $4.25 output. Reasoning tokens count as output. There is no long-context premium.

## Adapter

Use provider `meta` and model ID `muse-spark-1.3`. `build_model()` uses the installed Pydantic AI Responses adapter with base URL `https://api.meta.ai/v1` and `MODEL_API_KEY` from the host environment. It does not use `OPENAI_API_KEY` for Meta.

The adapter requests `reasoning.encrypted_content`, replays it between tool turns, preserves assistant `phase`, and sets `store=false`. The model profile enables these capabilities explicitly because the library's OpenAI model-name lookup does not recognize Muse Spark.

The smoke plan uses standard mode. Contributor-mode model IDs are not configured. The router's automatic policy has no Muse Spark capability prior yet. The lab can assign it directly and collect measured evidence first.

## Run one coding task

Add `MODEL_API_KEY` to the project's untracked `.env`, then run:

```sh
set -a
. ./.env
set +a
uv run lab plan plans/smoke-meta.toml
uv run lab run plans/smoke-meta.toml
```

The lab runs task admission, starts the worker in Docker, verifies its patch with hidden tests in a fresh container, and saves usage, cost, latency, and artifacts under a new run directory. Worker and lab spending caps remain disabled.

## Validation on 2026-10-14

The adapter passed a synthetic HTTP check for endpoint, authentication, reasoning effort, encrypted reasoning replay, commentary phases, tool outputs, token usage, and pricing. This check made no model API calls.

Live run `review-pr1-meta-spark-20261014` passed task admission, patch application, protected-path checks, and hidden pytest tests for `typedkey-kwargs`. Muse Spark used 7 requests, 42.459 seconds, and $0.044249 at the documented standard-mode rates. Recorded usage was 49,324 input tokens, including 22,995 cache reads, and 1,856 output tokens. These totals match the saved transcript.
