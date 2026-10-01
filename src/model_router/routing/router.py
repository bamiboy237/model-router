from collections.abc import Callable, Collection
from dataclasses import dataclass

from model_router.contracts import Candidate, DecisionReceipt, Feature, ModelRef, TokenUsage
from model_router.routing.config import RouterConfig, model_key, model_ref
from model_router.routing.facts import TaskFacts
from model_router.routing.request import DelegationRequest
from model_router.workers.config import PriceTable, UnpricedModelError


class NoEligibleModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Option:
    key: str
    ref: ModelRef
    success: float
    cost: int


# Extra violations for one model, given its success estimate.
_Constraint = Callable[[ModelRef, float | None], list[str]]


def route(
    request: DelegationRequest, facts: TaskFacts, config: RouterConfig, prices: PriceTable
) -> DecisionReceipt:
    candidates, options = _evaluate(request, facts, config, prices, lambda ref, est: [])
    chosen, rationale = _pick(options, config)
    verdicts = {o.ref: _verdict(o, chosen, options, config) for o in options}
    return _receipt(request, facts, config, candidates, verdicts, chosen, rationale)


def escalate(
    request: DelegationRequest,
    facts: TaskFacts,
    config: RouterConfig,
    prices: PriceTable,
    *,
    failed: ModelRef,
    tried: Collection[ModelRef],
) -> DecisionReceipt:
    """Pick the cheapest untried model with a higher success estimate than the failed one."""
    spec = config.models.get(model_key(failed))
    prior = spec.prior(request.kind, request.domain) if spec else None
    floor = prior[0] if prior else 0.0

    def stronger_and_untried(ref: ModelRef, estimate: float | None) -> list[str]:
        if ref in tried:
            return ["already_tried"]
        if estimate is not None and estimate <= floor:
            return ["not_stronger"]
        return []

    candidates, options = _evaluate(request, facts, config, prices, stronger_and_untried)
    chosen = min(options, key=lambda o: (o.cost, -o.success, o.key))
    verdicts = {
        o.ref: "selected" if o is chosen else "costs more than the selected model" for o in options
    }
    rationale = (
        f"cheapest untried model with expected success above {floor:.2f}, "
        f"the estimate for {model_key(failed)}"
    )
    return _receipt(request, facts, config, candidates, verdicts, chosen, rationale)


def _evaluate(
    request: DelegationRequest,
    facts: TaskFacts,
    config: RouterConfig,
    prices: PriceTable,
    constraint: _Constraint,
) -> tuple[list[Candidate], list[_Option]]:
    candidates: list[Candidate] = []
    options: list[_Option] = []
    for key, spec in sorted(config.models.items()):
        ref = model_ref(key)
        violations: list[str] = []
        cost = _expected_cost(request, facts, config, prices, ref)
        if cost is None:
            violations.append("unpriced")
        if facts.context_tokens > spec.context_limit:
            violations.append("context_too_large")
        if not spec.tool_support:
            violations.append("no_tool_support")
        estimate = spec.prior(request.kind, request.domain)
        if estimate is None:
            violations.append("no_success_estimate")
        violations += constraint(ref, estimate[0] if estimate else None)
        candidates.append(
            Candidate(
                model=ref,
                score=estimate[0] if estimate else None,
                expected_cost_micro_usd=cost,
                constraint_violations=tuple(violations),
                reason=_reason(estimate, cost, violations),
            )
        )
        if not violations and estimate is not None and cost is not None:
            options.append(_Option(key, ref, estimate[0], cost))
    if not options:
        details = "; ".join(f"{c.model.provider}:{c.model.model_id} {c.reason}" for c in candidates)
        raise NoEligibleModelError(f"no model can take this job: {details}")
    return candidates, options


def _receipt(
    request: DelegationRequest,
    facts: TaskFacts,
    config: RouterConfig,
    candidates: list[Candidate],
    verdicts: dict[ModelRef, str],
    chosen: _Option,
    rationale: str,
) -> DecisionReceipt:
    candidates = [
        c.model_copy(update={"reason": f"{c.reason}; {verdicts[c.model]}"})
        if c.model in verdicts
        else c
        for c in candidates
    ]
    return DecisionReceipt(
        decision_id=f"{request.task_id}:{config.policy_version}",
        policy_version=config.policy_version,
        task_features=_features(request, facts, config),
        candidates=tuple(candidates),
        selected=chosen.ref,
        role=config.roles[request.kind],
        rationale=rationale,
    )


def _expected_cost(
    request: DelegationRequest,
    facts: TaskFacts,
    config: RouterConfig,
    prices: PriceTable,
    ref: ModelRef,
) -> int | None:
    usage = config.usage[request.kind]
    tokens = TokenUsage(
        input_tokens=usage.input_tokens + facts.context_tokens,
        output_tokens=usage.output_tokens,
    )
    try:
        return prices.cost_micro_usd(ref, tokens)
    except UnpricedModelError:
        return None


def _pick(options: list[_Option], config: RouterConfig) -> tuple[_Option, str]:
    def best_success(pool: list[_Option]) -> _Option:
        return min(pool, key=lambda o: (-o.success, o.cost, o.key))

    if config.pick_rule == "best_success":
        return best_success(options), "highest expected success; cost breaks ties"
    if config.pick_rule == "best_value":
        chosen = min(options, key=lambda o: (-o.success / max(o.cost, 1), -o.success, o.key))
        return chosen, "highest expected success per dollar"
    above = [o for o in options if o.success >= config.min_success]
    if above:
        chosen = min(above, key=lambda o: (o.cost, -o.success, o.key))
        return chosen, f"cheapest model with expected success >= {config.min_success:.2f}"
    return best_success(options), (
        f"no model reaches expected success {config.min_success:.2f}; "
        "fell back to the highest expected success"
    )


def _verdict(option: _Option, chosen: _Option, options: list[_Option], config: RouterConfig) -> str:
    if option is chosen:
        return "selected"
    if config.pick_rule == "best_value":
        return "lower expected success per dollar than the selected model"
    reaches_bar = any(o.success >= config.min_success for o in options)
    if config.pick_rule == "cheapest_above" and reaches_bar:
        if option.success < config.min_success:
            return f"expected success below {config.min_success:.2f}"
        return "costs more than the selected model"
    if option.success < chosen.success:
        return "lower expected success than the selected model"
    return "same expected success, costs more"


def _reason(estimate: tuple[float, str] | None, cost: int | None, violations: list[str]) -> str:
    parts = []
    if estimate is not None:
        parts.append(f"expected success {estimate[0]:.2f} from prior '{estimate[1]}'")
    if cost is not None:
        parts.append(f"expected cost ${cost / 1_000_000:.4f}")
    if violations:
        parts.append("rejected: " + ", ".join(violations))
    return "; ".join(parts) or "no estimate"


def _features(
    request: DelegationRequest, facts: TaskFacts, config: RouterConfig
) -> dict[str, Feature]:
    features: dict[str, Feature] = {
        "kind": str(request.kind),
        "file_count": facts.file_count,
        "context_tokens": facts.context_tokens,
        "language": facts.language,
        "pick_rule": config.pick_rule,
        "min_success": config.min_success,
    }
    if request.domain is not None:
        features["domain"] = str(request.domain)
    return features
