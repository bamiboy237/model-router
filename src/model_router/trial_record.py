from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from model_router.contracts import (
    SCHEMA_VERSION,
    AttemptCause,
    CheckResult,
    Contract,
    Domain,
    ErrorCode,
    ExecutionTrace,
    Feature,
    Id,
    Kind,
    ModelRef,
    NonNegativeInt,
    ResultStatus,
    Sha256,
    TokenUsage,
    outcome_status,
    require_status,
)


class Latency(Contract):
    model_ms: NonNegativeInt
    verification_ms: NonNegativeInt
    total_ms: NonNegativeInt

    @model_validator(mode="after")
    def _total_covers_parts(self) -> Self:
        if self.total_ms < self.model_ms + self.verification_ms:
            raise ValueError("total_ms is shorter than model_ms plus verification_ms")
        return self


class LabInfo(Contract):
    trial_id: UUID
    run_id: Id
    plan_hash: Sha256
    repetition: NonNegativeInt
    task_family: Id
    artifacts_path: Id


class TrialRecord(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    trace_id: Id
    task_id: Id
    kind: Kind
    domain: Domain | None
    task_features: dict[str, Feature]
    attempt_id: Id
    parent_attempt_id: Id | None
    cause: AttemptCause
    attempt_index: NonNegativeInt
    started_at: AwareDatetime
    policy_version: Id
    role: Id
    model: ModelRef
    context_strategy: Id
    context_token_estimate: NonNegativeInt
    context_ref_count: NonNegativeInt
    usage: TokenUsage
    cost_micro_usd: NonNegativeInt
    latency: Latency
    required_checks: tuple[Id, ...]
    checks: tuple[CheckResult, ...]
    status: ResultStatus
    error_code: ErrorCode | None
    patch_hash: Sha256 | None
    lab: LabInfo | None = Field(default=None, description="Set only for rows written by trial_lab.")

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> Self:
        require_status(
            self.status, outcome_status(self.error_code, self.checks, self.required_checks)
        )
        return self


def trial_records(trace: ExecutionTrace, lab: LabInfo | None = None) -> tuple[TrialRecord, ...]:
    if lab is not None and len(trace.attempts) != 1:
        # trial_lab resumes runs by skipping recorded trial_ids, so one trial must be one row.
        raise ValueError("a lab trial must be a single-attempt trace")
    rows = []
    for index, attempt in enumerate(trace.attempts):
        result = attempt.result
        verification_ms = sum(c.duration_ms for c in attempt.checks)
        rows.append(
            TrialRecord(
                trace_id=trace.trace_id,
                task_id=trace.task.task_id,
                kind=trace.task.kind,
                domain=trace.task.domain,
                role=attempt.decision.role,
                task_features=attempt.decision.task_features,
                attempt_id=attempt.attempt_id,
                parent_attempt_id=attempt.parent_attempt_id,
                cause=attempt.cause,
                attempt_index=index,
                started_at=attempt.started_at,
                policy_version=attempt.decision.policy_version,
                model=result.model,
                context_strategy=attempt.context.strategy,
                context_token_estimate=attempt.context.token_estimate,
                context_ref_count=len(attempt.context.refs),
                usage=result.usage,
                cost_micro_usd=result.cost_micro_usd,
                latency=Latency(
                    model_ms=result.latency_ms,
                    verification_ms=verification_ms,
                    total_ms=attempt.active_ms,
                ),
                required_checks=attempt.plan,
                checks=attempt.checks,
                status=attempt.status,
                error_code=result.error_code,
                patch_hash=result.patch_hash,
                lab=lab,
            )
        )
    return tuple(rows)

