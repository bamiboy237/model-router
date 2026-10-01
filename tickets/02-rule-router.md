# Ticket 02: Build the rule-based router

## Stage

Beginning

## Goal

Select a worker from explicit task requirements and configurable capability priors.

## Scope

- Tag each task with a kind (`explore`, `review`, `fix`, `build`, `refactor`, `test`, `design`, `docs`). Code-editing kinds also take a domain (`frontend`, `backend`, `data`, `infra`, `general`).
- Measure task facts from the repository: linked file count, context tokens, and dominant language.
- Add model metadata: context limit, price, and success priors per tag.
- Reject models that violate hard task constraints.
- Select an eligible model with a configurable pick rule.
- Return a decision receipt with every candidate, its expected success and cost, and why it won or lost.

## Acceptance criteria

- The router rejects ineligible models.
- The receipt includes task requirements, eligible models, selected model, and rule matches.
- Configuration changes alter routing without code changes.
- Equal inputs produce equal decisions.

## Validation

Run `ruff`, `mypy --strict`, and the schema check. Then run a throwaway script that routes fixed requests and checks determinism, constraint filtering, pick rules, tag validation, and loser reasons.

## Decisions

- **Roles and models are separate.** A role (`config/workers.toml`) holds instructions and limits. The router maps the task kind to a role, then picks a model from `config/router.toml`.
- **Two tag axes.** Kind says what activity the task is. Domain says which part of the codebase a code edit touches. The request rejects a domain on a kind that does not edit code, and requires one on a kind that does.
- **Measured facts, not caller claims.** The router reads linked files from git at `base_sha` and estimates context tokens at 4 bytes per token. The caller does not supply these numbers.
- **Hard filters run first.** A model is ineligible if the linked context exceeds its context limit, if it has no price, if it lacks tool support, or if no success prior matches the task. If every model is ineligible, the router raises `NoEligibleModelError` with each model's reason.
- **Pick rules.** `cheapest_above` picks the cheapest model whose expected success is at least `min_success`. `best_success` picks the highest expected success, with cost breaking ties. `best_value` picks the highest success per dollar. If no model clears `min_success`, `cheapest_above` falls back to `best_success` and says so in the receipt.
- **Priors match most specific first:** `<kind>/<domain>`, then `<kind>`, then `*`. The receipt names the prior that was used.
- **Expected cost** is the usage estimate for the kind, plus linked context tokens, priced with `config/prices.toml` in exact micro-USD.
- **Traceability.** Every receipt carries `policy_version`. Change it whenever `config/router.toml` changes.

## Limitations

- Success priors and usage estimates are guesses. Ticket `06` replaces them with measured rates and medians from trial records.
- Token counts use a byte heuristic, not a real tokenizer.
- Latency is not a routing input yet.
- DeepSeek is priced but not routable until the worker can build a DeepSeek model.
