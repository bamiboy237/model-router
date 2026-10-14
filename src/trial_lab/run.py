"""Stage 1 runs: every arm tries every task once per repetition, in the plan's shuffled order.

A trial is one attempt with no retry or escalation. It becomes one TrialRecord row that also
holds the rule-based router's shadow receipt. A provider error (rate limit, outage, network)
says nothing about the model, so it is logged to errors.jsonl and the trial stays pending.
"""

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai.models import Model

from model_router.contracts import (
    PROVIDER_ERRORS,
    Attempt,
    AttemptCause,
    Candidate,
    ContextPacket,
    DecisionReceipt,
    ExecutionBudget,
    ExecutionTrace,
    ResultStatus,
    StopReason,
    StopReceipt,
    TaskSpec,
    TokenUsage,
    outcome_status,
)
from model_router.routing import DelegationRequest, RouterConfig, load_router_config, measure, route
from model_router.trial_record import LabInfo, TrialRecord, trial_records
from model_router.verification import verify
from model_router.workers import (
    HARNESS_VERSION,
    PriceTable,
    SandboxConfig,
    UnpricedModelError,
    WorkerRole,
    build_model,
    load_prices,
    load_roles,
    run_worker,
)
from trial_lab.plan import Arm, Plan, PlanFile, Trial, build_trials
from trial_lab.store import RunStore
from trial_lab.tasks import LabTask

# This many provider errors in a row stops the run: the provider is down or the key is limited.
MAX_PROVIDER_ERRORS_IN_A_ROW = 3
Report = Callable[[str], None]


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    router: RouterConfig
    prices: PriceTable
    roles: Mapping[str, WorkerRole]


def load_settings(config_dir: Path) -> Settings:
    return Settings(
        router=load_router_config(config_dir / "router.toml"),
        prices=load_prices(config_dir / "prices.toml"),
        roles=load_roles(config_dir / "workers.toml"),
    )


@dataclass(frozen=True)
class PreparedTask:
    task: LabTask
    spec: TaskSpec
    context: ContextPacket
    role: WorkerRole
    receipt: DecisionReceipt


@dataclass(frozen=True)
class PreparedPlan:
    file: PlanFile
    plan: Plan
    settings: Settings
    trials: tuple[Trial, ...]
    tasks: Mapping[str, PreparedTask]
    arms: Mapping[str, Arm]
    # Expected micro-USD per (task_id, arm_id), from the router's usage guesses.
    estimates: Mapping[tuple[str, str], int]

    @property
    def estimate_micro_usd(self) -> int:
        return sum(self.estimates[t.task_id, t.arm_id] for t in self.trials)


def prepare(file: PlanFile, corpus: Sequence[LabTask], settings: Settings) -> PreparedPlan:
    """Resolve the plan and price every trial. Makes no model call."""
    if settings.prices.version != file.prices:
        raise PlanError(
            f"the plan expects price table {file.prices}, but config has {settings.prices.version}"
        )
    for arm in file.arms:
        try:
            settings.prices.price_for(arm.model)
        except UnpricedModelError as error:
            raise PlanError(f"arm {arm.arm_id}: {error}") from error
    plan = file.resolve(corpus)
    by_id = {t.task_id: t for t in corpus}
    tasks = {task_id: _prepare_task(by_id[task_id], settings) for task_id in plan.task_ids}
    estimates = {}
    for task_id, prepared in tasks.items():
        guess = settings.router.usage[prepared.spec.kind]
        tokens = TokenUsage(
            input_tokens=guess.input_tokens + prepared.context.token_estimate,
            output_tokens=guess.output_tokens,
        )
        for arm in plan.arms:
            estimates[task_id, arm.arm_id] = settings.prices.cost_micro_usd(arm.model, tokens)
    return PreparedPlan(
        file=file,
        plan=plan,
        settings=settings,
        trials=build_trials(plan),
        tasks=tasks,
        arms={arm.arm_id: arm for arm in plan.arms},
        estimates=estimates,
    )


def _prepare_task(task: LabTask, settings: Settings) -> PreparedTask:
    spec = task.spec()
    request = DelegationRequest(
        repo=spec.repo,
        base_sha=spec.base_sha,
        kind=spec.kind,
        domain=spec.domain,
        overview=spec.overview,
        task=spec.instruction,
        files=tuple(ref.path for ref in spec.context_refs),
        checks=spec.verifiers,
        protected_paths=spec.protected_paths,
    )
    facts = measure(request)
    receipt = route(request, facts, settings.router, settings.prices)
    context = ContextPacket(
        packet_id=f"{spec.task_id}:task_files",
        task_id=spec.task_id,
        strategy="task_files",
        refs=spec.context_refs,
        token_estimate=facts.context_tokens,
    )
    role = settings.roles[receipt.role]
    return PreparedTask(task, spec, context, role, receipt)


@dataclass
class RunSummary:
    recorded: int = 0
    provider_errors: int = 0
    spent_micro_usd: int = 0
    skipped: int = 0
    stopped: str | None = None
    failure: BaseException | None = None
    _reserved: int = 0
    _errors_in_a_row: int = 0
    _observed: dict[str, int] = field(default_factory=dict)


async def run_plan(
    prepared: PreparedPlan,
    store: RunStore,
    *,
    run_id: str,
    models: Mapping[str, Model] | None = None,
    report: Report = print,
) -> RunSummary:
    """Run every trial not yet in the store. Pass models, keyed by arm id, to script workers.

    Before it starts a trial, the runner reserves the trial's expected cost: the larger of the
    router's guess and the highest cost the arm has recorded. It starts no trial whose
    reservation would take spend past max_usd.
    """
    plan = prepared.plan
    workers = {
        arm.arm_id: (models or {}).get(arm.arm_id) or build_model(arm.model) for arm in plan.arms
    }
    records = store.records()
    if any(r.lab is None or r.lab.plan_hash != plan.plan_hash for r in records):
        raise PlanError(f"{store.trials} holds trials from a different plan")
    done = {r.lab.trial_id for r in records if r.lab is not None}
    summary = RunSummary(
        skipped=len(done),
        spent_micro_usd=sum(r.cost_micro_usd for r in records) + store.error_cost_micro_usd(),
    )
    for record in records:
        if record.lab is not None:
            arm_id = record.lab.arm_id
            summary._observed[arm_id] = max(summary._observed.get(arm_id, 0), record.cost_micro_usd)
    limit = int(prepared.file.max_usd * 1_000_000)
    pending = [t for t in prepared.trials if t.trial_id not in done]
    total = len(prepared.trials)
    slots = asyncio.Semaphore(prepared.file.concurrency)
    running: list[asyncio.Task[None]] = []

    async def one(trial: Trial, reserved: int) -> None:
        try:
            record = await run_trial(prepared, trial, store, run_id, workers[trial.arm_id])
        except Exception as error:
            summary.failure = error
            summary.stopped = f"trial {trial.trial_id} failed: {type(error).__name__}: {error}"
            return
        finally:
            summary._reserved -= reserved
            slots.release()
        line = f"[{trial.ordinal}/{total}] {trial.task_id} {trial.arm_id} r{trial.repetition}"
        if isinstance(record, TrialRecord):
            summary.recorded += 1
            summary._errors_in_a_row = 0
            summary.spent_micro_usd += record.cost_micro_usd
            seen = summary._observed.get(trial.arm_id, 0)
            summary._observed[trial.arm_id] = max(seen, record.cost_micro_usd)
            failed = [c.verifier_name for c in record.checks if c.passed is False]
            detail = record.error_code or ", ".join(failed)
            report(f"{line}: {record.status}{f' ({detail})' if detail else ''}, "
                   f"${record.cost_micro_usd / 1e6:.4f}, {record.latency.total_ms / 1000:.1f}s")
        else:
            error_code, cost = record
            summary.provider_errors += 1
            summary._errors_in_a_row += 1
            summary.spent_micro_usd += cost
            report(f"{line}: {error_code}; left pending")
            if summary._errors_in_a_row >= MAX_PROVIDER_ERRORS_IN_A_ROW:
                summary.stopped = f"{summary._errors_in_a_row} provider errors in a row"

    def over(reserve: int) -> bool:
        return summary.spent_micro_usd + summary._reserved + reserve > limit

    for trial in pending:
        await slots.acquire()
        guess = prepared.estimates[trial.task_id, trial.arm_id]
        reserve = max(guess, summary._observed.get(trial.arm_id, 0))
        # Finished trials free their reservations, so wait for them before giving up.
        while over(reserve) and not summary.stopped:
            busy = [t for t in running if not t.done()]
            if not busy:
                break
            await asyncio.wait(busy, return_when=asyncio.FIRST_COMPLETED)
            reserve = max(guess, summary._observed.get(trial.arm_id, 0))
        if summary.stopped:
            slots.release()
            break
        if over(reserve):
            slots.release()
            summary.stopped = (
                f"budget: ${summary.spent_micro_usd / 1e6:.2f} spent and "
                f"${summary._reserved / 1e6:.2f} reserved; the next trial may cost "
                f"${reserve / 1e6:.2f} of max ${prepared.file.max_usd}"
            )
            break
        summary._reserved += reserve
        running.append(asyncio.create_task(one(trial, reserve)))
    await asyncio.gather(*running)
    return summary


async def run_trial(
    prepared: PreparedPlan,
    trial: Trial,
    store: RunStore,
    run_id: str,
    model: Model,
) -> TrialRecord | tuple[str, int]:
    """Run, verify, and record one trial. Returns the record, or the provider error and cost."""
    task = prepared.tasks[trial.task_id]
    arm = prepared.arms[trial.arm_id]
    settings = prepared.settings
    attempt_id = f"{trial.trial_id}:0"
    sandbox = SandboxConfig(image=task.task.file.image)
    started_at = datetime.now(UTC)
    clock = time.monotonic()
    result = await run_worker(
        task=task.spec,
        context=task.context,
        role=task.role,
        model_ref=arm.model,
        attempt_id=attempt_id,
        prices=settings.prices,
        sandbox_config=sandbox,
        model=model,
        thinking=arm.thinking,
        code_mode=arm.code_mode,
    )
    artifacts = store.artifacts(trial.trial_id)
    (artifacts / "transcript.json").write_text(result.transcript)
    if result.error_message:
        (artifacts / "error.txt").write_text(result.error_message)
    if result.error_code in PROVIDER_ERRORS:
        store.add_error(trial.trial_id, result.error_code, result.cost_micro_usd)
        return str(result.error_code), result.cost_micro_usd
    verification = None
    if result.patch is not None:
        (artifacts / "patch.diff").write_text(result.patch)
        verification = await verify(task.spec, result.patch, sandbox)
        if verification.note:
            (artifacts / "verification.txt").write_text(verification.note)
    active_ms = int((time.monotonic() - clock) * 1000)
    checks = verification.result.checks if verification else ()
    required = verification.result.required if verification else ()
    status = outcome_status(result.error_code, checks, required)
    attempt = Attempt(
        attempt_id=attempt_id,
        parent_attempt_id=None,
        cause=AttemptCause.INITIAL,
        started_at=started_at,
        active_ms=active_ms,
        decision=_assignment(prepared, trial, arm, task, attempt_id),
        context=task.context,
        result=result.summary(),
        verification=verification.result if verification else None,
        status=status,
    )
    trace = ExecutionTrace(
        trace_id=f"trial-{trial.trial_id}",
        task=task.spec.summary(),
        budget=ExecutionBudget(
            max_attempts=1,
            max_cost_micro_usd=_max_cost(task.role, arm, settings),
            max_active_ms=int(
                (task.role.time_budget_s + sum(v.timeout_s for v in task.spec.verifiers)) * 1000
            ),
        ),
        attempts=(attempt,),
        stop=_stop(status, result.cost_micro_usd, active_ms),
        final_status=status,
    )
    lab = LabInfo(
        trial_id=trial.trial_id,
        run_id=run_id,
        plan_hash=prepared.plan.plan_hash,
        arm_id=arm.arm_id,
        thinking=arm.thinking,
        code_mode=arm.code_mode,
        harness_version=HARNESS_VERSION,
        repetition=trial.repetition,
        task_family=task.task.file.family,
        artifacts_path=str(artifacts.relative_to(store.root)),
        router_receipt=task.receipt,
    )
    (record,) = trial_records(trace, lab)
    store.add_record(record)
    return record


def _assignment(
    prepared: PreparedPlan, trial: Trial, arm: Arm, task: PreparedTask, attempt_id: str
) -> DecisionReceipt:
    return DecisionReceipt(
        decision_id=attempt_id,
        policy_version=f"lab.{prepared.plan.assignment}",
        task_features=task.receipt.task_features,
        candidates=(
            Candidate(
                model=arm.model,
                score=None,
                expected_cost_micro_usd=prepared.estimates[trial.task_id, arm.arm_id],
                reason=f"arm {arm.arm_id}",
            ),
        ),
        selected=arm.model,
        role=task.receipt.role,
        rationale="stage 1 assigns every arm to every task",
    )


def _max_cost(role: WorkerRole, arm: Arm, settings: Settings) -> int:
    if role.max_cost_usd is not None:
        return int(role.max_cost_usd * 1_000_000)
    assert role.max_total_tokens is not None
    # All output is the worst case under a token limit.
    tokens = TokenUsage(output_tokens=role.max_total_tokens)
    return settings.prices.cost_micro_usd(arm.model, tokens)


def _stop(status: ResultStatus, cost_micro_usd: int, active_ms: int) -> StopReceipt:
    if status == ResultStatus.SUCCESS:
        reason, detail = StopReason.ACCEPTED, "every required check passed"
    elif status == ResultStatus.UNCERTAIN:
        reason, detail = StopReason.UNVERIFIED, "a required check timed out or could not run"
    else:
        reason, detail = StopReason.ATTEMPTS_EXHAUSTED, "stage 1 trials take one attempt"
    return StopReceipt(
        reason=reason,
        detail=detail,
        attempt_count=1,
        cost_micro_usd=cost_micro_usd,
        active_ms=active_ms,
    )
