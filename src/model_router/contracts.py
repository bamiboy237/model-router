from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal[1] = 1

Id = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Feature = str | int | float | bool


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Kind(StrEnum):
    EXPLORE = "explore"
    REVIEW = "review"
    FIX = "fix"
    BUILD = "build"
    REFACTOR = "refactor"
    TEST = "test"
    DESIGN = "design"
    DOCS = "docs"


class Domain(StrEnum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATA = "data"
    INFRA = "infra"
    GENERAL = "general"


CODE_EDITING_KINDS = frozenset({Kind.FIX, Kind.BUILD, Kind.REFACTOR, Kind.TEST})


def require_domain_matches_kind(kind: Kind, domain: Domain | None) -> None:
    if (kind in CODE_EDITING_KINDS) != (domain is not None):
        raise ValueError("fix, build, refactor, and test need a domain; other kinds take none")


class ResultStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class AttemptCause(StrEnum):
    INITIAL = "initial"
    RETRY = "retry"
    ESCALATION = "escalation"


class ErrorCode(StrEnum):
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NETWORK_ERROR = "network_error"
    CONTEXT_TOO_LONG = "context_too_long"
    REFUSED = "refused"
    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    INVALID_OUTPUT = "invalid_output"
    PATCH_APPLY_FAILED = "patch_apply_failed"


# These describe the provider, not the model, so they are not evidence about its ability.
# Labeling them as failures would teach the router that a model is bad when the provider was down.
_UNCERTAIN_ERRORS = frozenset(
    {ErrorCode.RATE_LIMITED, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.NETWORK_ERROR}
)


class ModelRef(Contract):
    provider: Id
    model_id: Id


class ContextRef(Contract):
    kind: Literal["file", "symbol", "doc"]
    path: Id
    content_hash: Sha256 | None = None


class VerifierSpec(Contract):
    name: Id
    version: Id
    kind: Literal["tests", "typecheck", "lint"]
    command: tuple[Id, ...] = Field(min_length=1)
    timeout_s: float = Field(gt=0)
    required: bool = True


class TaskSpec(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    task_id: Id
    kind: Kind
    domain: Domain | None = None
    overview: str = ""
    instruction: Id
    repo: Id
    base_sha: str = Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")
    context_refs: tuple[ContextRef, ...] = ()
    verifiers: tuple[VerifierSpec, ...] = ()

    @model_validator(mode="after")
    def _valid_tags_and_verifiers(self) -> Self:
        require_domain_matches_kind(self.kind, self.domain)
        _require_unique((v.name for v in self.verifiers), "verifier name")
        return self


class ContextPacket(Contract):
    packet_id: Id
    task_id: Id
    strategy: Id
    refs: tuple[ContextRef, ...]
    token_estimate: NonNegativeInt


class TokenUsage(Contract):
    input_tokens: NonNegativeInt = 0
    output_tokens: NonNegativeInt = 0
    cache_read_tokens: NonNegativeInt = 0
    cache_write_tokens: NonNegativeInt = 0

    @model_validator(mode="after")
    def _cache_within_input(self) -> Self:
        if self.cache_read_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("cache tokens are counted inside input_tokens and cannot exceed it")
        return self


class TaskResult(Contract):
    task_id: Id
    attempt_id: Id
    model: ModelRef
    patch: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    usage: TokenUsage
    cost_micro_usd: NonNegativeInt
    latency_ms: NonNegativeInt

    @model_validator(mode="after")
    def _patch_xor_error(self) -> Self:
        if (self.patch is None) == (self.error_code is None):
            raise ValueError("a worker result needs exactly one of patch or error_code")
        if self.error_message is not None and self.error_code is None:
            raise ValueError("error_message requires error_code")
        return self


class CheckResult(Contract):
    verifier_name: Id
    verifier_version: Id
    required: bool
    passed: bool | None
    exit_code: int | None
    duration_ms: NonNegativeInt
    output_hash: Sha256 | None = None


def verification_status(checks: Iterable[CheckResult]) -> ResultStatus:
    required = [c.passed for c in checks if c.required]
    if False in required:
        return ResultStatus.FAILED
    if not required or None in required:
        return ResultStatus.UNCERTAIN
    return ResultStatus.SUCCESS


def outcome_status(error_code: ErrorCode | None, checks: Iterable[CheckResult]) -> ResultStatus:
    if error_code in _UNCERTAIN_ERRORS:
        return ResultStatus.UNCERTAIN
    if error_code is not None:
        return ResultStatus.FAILED
    return verification_status(checks)


class VerificationResult(Contract):
    checks: tuple[CheckResult, ...] = Field(min_length=1)
    status: ResultStatus

    @model_validator(mode="after")
    def _status_matches_checks(self) -> Self:
        _require_unique((c.verifier_name for c in self.checks), "verifier name")
        require_status(self.status, verification_status(self.checks))
        return self


class Candidate(Contract):
    model: ModelRef
    score: float | None
    expected_cost_micro_usd: NonNegativeInt | None = None
    constraint_violations: tuple[Id, ...] = ()
    reason: Id


class DecisionReceipt(Contract):
    decision_id: Id
    policy_version: Id
    task_features: dict[str, Feature]
    candidates: tuple[Candidate, ...] = Field(min_length=1)
    selected: ModelRef
    role: Id
    rationale: Id

    @model_validator(mode="after")
    def _selected_is_valid_candidate(self) -> Self:
        _require_unique((c.model for c in self.candidates), "candidate model")
        chosen = [c for c in self.candidates if c.model == self.selected]
        if not chosen:
            raise ValueError("selected model is not among the candidates")
        if chosen[0].constraint_violations:
            raise ValueError("selected candidate violates constraints")
        return self


class Attempt(Contract):
    attempt_id: Id
    parent_attempt_id: Id | None
    cause: AttemptCause
    started_at: AwareDatetime
    decision: DecisionReceipt
    context: ContextPacket
    result: TaskResult
    verification: VerificationResult | None
    status: ResultStatus

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.cause == AttemptCause.INITIAL) != (self.parent_attempt_id is None):
            raise ValueError("only the initial attempt has no parent")
        if self.result.attempt_id != self.attempt_id:
            raise ValueError("result.attempt_id does not match attempt_id")
        if self.result.model != self.decision.selected:
            raise ValueError("result model is not the model the decision selected")
        if self.context.task_id != self.result.task_id:
            raise ValueError("context packet belongs to a different task")
        if self.result.error_code is not None and self.verification is not None:
            raise ValueError("a worker error has no patch to verify")
        require_status(self.status, outcome_status(self.result.error_code, self.checks))
        return self

    @property
    def checks(self) -> tuple[CheckResult, ...]:
        return self.verification.checks if self.verification else ()


class ExecutionTrace(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    trace_id: Id
    task: TaskSpec
    attempts: tuple[Attempt, ...] = Field(min_length=1)
    final_status: ResultStatus

    @model_validator(mode="after")
    def _valid_lineage(self) -> Self:
        _require_unique((a.attempt_id for a in self.attempts), "attempt_id")
        if self.attempts[0].cause != AttemptCause.INITIAL:
            raise ValueError("the first attempt must be the initial attempt")
        earlier: dict[str, Attempt] = {}
        for attempt in self.attempts:
            if attempt.result.task_id != self.task.task_id:
                raise ValueError(f"attempt {attempt.attempt_id} ran a different task")
            if attempt.parent_attempt_id is not None:
                parent = earlier.get(attempt.parent_attempt_id)
                if parent is None:
                    raise ValueError(f"attempt {attempt.attempt_id} has no earlier parent")
                same_model = attempt.result.model == parent.result.model
                if attempt.cause == AttemptCause.ESCALATION and same_model:
                    raise ValueError(f"escalation {attempt.attempt_id} reused its parent's model")
            earlier[attempt.attempt_id] = attempt
        require_status(self.final_status, self.attempts[-1].status)
        return self


def _require_unique(values: Iterable[object], label: str) -> None:
    seen: list[object] = []
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.append(value)


def require_status(recorded: ResultStatus, expected: ResultStatus) -> None:
    if recorded != expected:
        raise ValueError(f"status {recorded} contradicts the evidence, which gives {expected}")
