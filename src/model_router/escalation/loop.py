import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_ai.models import Model

from model_router.contracts import (
    PROVIDER_ERRORS,
    Attempt,
    AttemptCause,
    DecisionReceipt,
    ExecutionBudget,
    ExecutionTrace,
    ModelRef,
    ResultStatus,
    StopReason,
    StopReceipt,
    outcome_status,
)
from model_router.routing import (
    DelegationRequest,
    NoEligibleModelError,
    RouterConfig,
    escalate,
    measure,
    model_key,
    route,
)
from model_router.verification import verify
from model_router.workers import PriceTable, SandboxConfig, WorkerRole, run_worker

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class TaskRun:
    trace: ExecutionTrace
    # Patches by attempt id, for the caller to apply or review. Never stored in the trace.
    patches: Mapping[str, str]


async def run_task(
    request: DelegationRequest,
    *,
    config: RouterConfig,
    prices: PriceTable,
    roles: Mapping[str, WorkerRole],
    budget: ExecutionBudget | None = None,
    sandbox: SandboxConfig | None = None,
    models: Mapping[ModelRef, Model] | None = None,
    trace_id: str | None = None,
    sleep: Sleep = asyncio.sleep,
) -> TaskRun:
    """Route, run, verify, and retry or escalate a task until it passes or a limit stops it.

    A model gets tries_per_model attempts with a note on what failed, then the cheapest
    untried model with a higher success estimate takes over. Provider errors retry the same
    model after a backoff and do not use up its tries. Pass models to script workers.
    """
    rules = config.escalation
    limits = rules.budget if budget is None else budget.within(rules.budget)
    task = request.to_task()
    facts = measure(request)
    context = request.to_context(facts.context_tokens)
    role = roles[config.roles[request.kind]]
    trace_id = trace_id or f"trace-{uuid4().hex[:16]}"

    receipt = route(request, facts, config, prices)
    cause, parent = AttemptCause.INITIAL, None
    tried = [receipt.selected]
    attempts: list[Attempt] = []
    patches: dict[str, str] = {}
    counted = model_tries = provider_tries = 0
    note: str | None = None
    started = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    def spent() -> int:
        return sum(a.result.cost_micro_usd for a in attempts)

    while True:
        stop = _budget_stop(limits, counted, spent(), elapsed_ms(), receipt)
        if stop is not None:
            break
        attempt_id = f"{trace_id}:{len(attempts)}"
        attempt_started = datetime.now(UTC)
        attempt_clock = time.monotonic()
        result = await run_worker(
            task=task,
            context=context,
            role=role,
            model_ref=receipt.selected,
            attempt_id=attempt_id,
            prices=prices,
            sandbox_config=sandbox,
            model=(models or {}).get(receipt.selected),
            note=note,
        )
        verification = None
        if result.patch is not None:
            verification = await verify(task, result.patch, sandbox)
        checks = verification.result.checks if verification else ()
        plan = verification.result.required if verification else ()
        attempt = Attempt(
            attempt_id=attempt_id,
            parent_attempt_id=parent,
            cause=cause,
            started_at=attempt_started,
            active_ms=int((time.monotonic() - attempt_clock) * 1000),
            decision=receipt.model_copy(update={"decision_id": attempt_id}),
            context=context,
            result=result.summary(),
            verification=verification.result if verification else None,
            status=outcome_status(result.error_code, checks, plan),
        )
        attempts.append(attempt)
        if result.patch is not None:
            patches[attempt_id] = result.patch
        parent = attempt_id
        current = model_key(receipt.selected)

        if attempt.status == ResultStatus.SUCCESS:
            stop = (StopReason.ACCEPTED, "every required check passed")
            break
        if result.error_code in PROVIDER_ERRORS:
            provider_tries += 1
            if provider_tries > rules.provider_retries:
                stop = (StopReason.PROVIDER_ERRORS, f"{current} gave {result.error_code} "
                        f"on {provider_tries} attempts in a row")
                break
            await sleep(rules.provider_backoff_s * 2 ** (provider_tries - 1))
            cause = AttemptCause.RETRY
            receipt = _rationale(receipt, f"provider retry {provider_tries} of "
                                 f"{rules.provider_retries} after {result.error_code}")
            continue
        provider_tries = 0
        counted += 1
        if attempt.status == ResultStatus.UNCERTAIN:
            stop = (StopReason.UNVERIFIED, _unverified_detail(plan))
            break

        model_tries += 1
        why = "failed checks" if verification else str(result.error_code)
        note = verification.note if verification else (
            f"It ended with {result.error_code}: {result.error_message or 'no details'}"
        )
        if model_tries < rules.tries_per_model:
            cause = AttemptCause.RETRY
            receipt = _rationale(receipt, f"try {model_tries + 1} of {rules.tries_per_model} "
                                 f"on {current} after {why}")
            continue
        try:
            receipt = escalate(request, facts, config, prices, failed=receipt.selected, tried=tried)
        except NoEligibleModelError:
            stop = (StopReason.NO_STRONGER_MODEL, f"{current} failed {model_tries} times and "
                    "no untried model has a higher success estimate")
            break
        tried.append(receipt.selected)
        cause = AttemptCause.ESCALATION
        model_tries = 0

    assert stop is not None  # every break above sets it
    reason, detail = stop
    trace = ExecutionTrace(
        trace_id=trace_id,
        task=task.summary(),
        budget=limits,
        attempts=tuple(attempts),
        stop=StopReceipt(
            reason=reason,
            detail=detail,
            attempt_count=len(attempts),
            cost_micro_usd=spent(),
            active_ms=elapsed_ms(),
        ),
        final_status=attempts[-1].status if attempts else ResultStatus.UNCERTAIN,
    )
    return TaskRun(trace, patches)


def _budget_stop(
    limits: ExecutionBudget, counted: int, spent: int, elapsed_ms: int, next_up: DecisionReceipt
) -> tuple[StopReason, str] | None:
    if counted >= limits.max_attempts:
        return StopReason.ATTEMPTS_EXHAUSTED, f"used all {limits.max_attempts} attempts"
    if elapsed_ms >= limits.max_active_ms:
        return StopReason.TIME_EXHAUSTED, f"used {elapsed_ms} of {limits.max_active_ms} ms"
    expected = next_up.expected_cost_micro_usd or 0
    if spent + expected > limits.max_cost_micro_usd:
        left = limits.max_cost_micro_usd - spent
        return StopReason.COST_EXHAUSTED, (
            f"the next attempt is expected to cost ${expected / 1e6:.4f}; ${left / 1e6:.4f} is left"
        )
    return None


def _rationale(receipt: DecisionReceipt, rationale: str) -> DecisionReceipt:
    return receipt.model_copy(update={"rationale": rationale})


def _unverified_detail(plan: tuple[str, ...]) -> str:
    if not plan:
        return "the task has no required checks; review the result and report the outcome"
    return "a required check timed out or could not run"
