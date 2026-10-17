# DeepSeek V4.1 Flash in the trial lab

Official references checked on 2026-10-14:

- [Models and pricing](https://api-docs.deepseek.com/quick_start/pricing/): the current model ID is `deepseek-flash`. The older Flash aliases serve V4.1 Flash too.
- [Model list](https://api-docs.deepseek.com/api/list-models/): `deepseek-flash` has a 1,048,576-token context window. The authenticated model list confirmed this ID is available.
- [Responses API](https://api-docs.deepseek.com/guides/responses_api/): streaming tools, raw reasoning replay, and cache-token accounting are supported. Requests are stateless.
- [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/): thinking is enabled by default. The smoke plan requests `medium`, which DeepSeek maps to `high`.

## Adapter

Use provider `deepseek` and model ID `deepseek-flash`. `build_model()` uses the installed Pydantic AI `DeepSeekProvider` and Responses adapter. The provider reads `DEEPSEEK_API_KEY` and sends requests to `https://api.deepseek.com/responses`.

The installed SDK's name lookup recognizes `deepseek-v4-*` but not `deepseek-flash`. The model profile therefore enables reasoning, declares its default, and supplies the context window. The provider's tool-choice restriction remains active during thinking. Provider defaults replay raw reasoning and keep function calls adjacent to their assistant messages. No dependency upgrade or worker prompt change is needed.

The model is selectable in lab plans and direct worker calls. Automatic routing priors remain unset until measured evidence supports them.

## Run one coding task

Add `DEEPSEEK_API_KEY` to the untracked `.env`, then run:

```sh
uv run --env-file .env lab plan plans/smoke-deepseek.toml
uv run --env-file .env lab run plans/smoke-deepseek.toml
```

The lab checks task admission, runs the worker in Docker, verifies its patch with hidden tests, and saves a new trial record.

## Price accounting

Table `2026-10-14-r1` already contains `deepseek:deepseek-flash`. Its peak rates per million tokens are $0.30 input, $0.006 cached input, and $1.20 output. Reasoning tokens count as output. The rates did not change, so the table version remains the same.

Off-peak rates are half the peak rates. Peak hours are 01:00–04:00 and 06:00–10:00 UTC on weekdays, excluding Chinese public holidays. The price table does not select rates by time. Recorded cost uses peak rates and can exceed the provider's off-peak charge. Cache writes have no separate premium.

## Validation on 2026-10-14

A throwaway synthetic HTTP check passed for the endpoint, DeepSeek authentication, model ID, reasoning effort, raw reasoning replay, parallel tool ordering, paired tool outputs, cache usage, pricing, and plan preparation. It made no model API calls. Raw reasoning is stored in transcript thinking parts under `provider_details.raw_content` and returns in the next request's reasoning `content`.

Live run `deepseek-v41-flash-smoke-20261014` passed task admission, patch application, protected-path checks, and hidden pytest tests for `typedkey-kwargs`. It used harness 4, CodeMode off, four requests, and 30.014 seconds. Recorded cost at peak rates was $0.004038. Usage was 21,575 input tokens, including 15,744 cache reads, and 1,828 output tokens. These totals matched the saved transcript. This single smoke validates integration, not general model quality.
