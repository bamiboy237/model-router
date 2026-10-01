import hashlib
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Literal[1] = 1

Id = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]
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
PROVIDER_ERRORS = frozenset(
    {ErrorCode.RATE_LIMITED, ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.NETWORK_ERROR}
)


class CheckReason(StrEnum):
    ASSERTION_FAILED = "assertion_failed"
    PATCH_CONFLICT = "patch_conflict"
    PROTECTED_PATH = "protected_path"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


_FAILING_REASONS = frozenset(
    {CheckReason.ASSERTION_FAILED, CheckReason.PATCH_CONFLICT, CheckReason.PROTECTED_PATH}
)

# The router adds these gates to every verification. They can fail an attempt,
# but passing them is not evidence that the task is done.
PATCH_APPLIES = "router.patch_applies"
PROTECTED_PATHS = "router.protected_paths"
ROUTER_CHECKS = (PATCH_APPLIES, PROTECTED_PATHS)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
    kind: Literal["tests", "typecheck", "lint", "browser"]
    command: tuple[Id, ...] = Field(min_length=1)
    timeout_s: float = Field(gt=0)
    required: bool = True

    @model_validator(mode="after")
    def _not_reserved(self) -> Self:
        if self.name.startswith("router."):
            raise ValueError("verifier names starting with 'router.' are reserved")
        return self


def required_checks(verifiers: Iterable[VerifierSpec]) -> tuple[str, ...]:
    return tuple(v.name for v in verifiers if v.required)


class TaskSpec(Contract):
    """A task as the worker sees it. Holds user content, so it is never stored in a trace."""

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
    protected_paths: tuple[Id, ...] = Field(
        default=(), description="Glob patterns. A patch that changes a matching path fails."
    )

    @model_validator(mode="after")
    def _valid_tags_and_verifiers(self) -> Self:
        require_domain_matches_kind(self.kind, self.domain)
        _require_unique((v.name for v in self.verifiers), "verifier name")
        return self

    def summary(self) -> "TaskSummary":
        return TaskSummary(
            task_id=self.task_id,
            kind=self.kind,
            domain=self.domain,
            content_hash=sha256_text(f"{self.overview}\n{self.instruction}"),
            repo_hash=sha256_text(self.repo),
            base_sha=self.base_sha,
            context_refs=self.context_refs,
            verifiers=self.verifiers,
            protected_paths=self.protected_paths,
        )


class TaskSummary(Contract):
    """The stored form of a task: hashes in place of the instruction text and repo location."""

    task_id: Id
    kind: Kind
    domain: Domain | None
    content_hash: Sha256
    repo_hash: Sha256
    base_sha: str = Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")
    context_refs: tuple[ContextRef, ...]
    verifiers: tuple[VerifierSpec, ...]
    protected_paths: tuple[Id, ...]

    @model_validator(mode="after")
    def _valid_tags(self) -> Self:
        require_domain_matches_kind(self.kind, self.domain)
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
    """A worker's output. Holds the patch and provider text, so it is never stored in a trace."""

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

    def summary(self) -> "ResultSummary":
        return ResultSummary(
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            model=self.model,
            patch_hash=sha256_text(self.patch) if self.patch is not None else None,
            patch_bytes=len(self.patch.encode()) if self.patch is not None else None,
            error_code=self.error_code,
            usage=self.usage,
            cost_micro_usd=self.cost_micro_usd,
            latency_ms=self.latency_ms,
        )


class ResultSummary(Contract):
    """The stored form of a worker result: a patch fingerprint in place of the patch."""

    task_id: Id
    attempt_id: Id
    model: ModelRef
    patch_hash: Sha256 | None
    patch_bytes: NonNegativeInt | None
    error_code: ErrorCode | None
    usage: TokenUsage
    cost_micro_usd: NonNegativeInt
    latency_ms: NonNegativeInt

    @model_validator(mode="after")
    def _patch_xor_error(self) -> Self:
        if (self.patch_hash is None) == (self.error_code is None):
            raise ValueError("a worker result needs exactly one of patch_hash or error_code")
        if (self.patch_hash is None) != (self.patch_bytes is None):
            raise ValueError("patch_bytes goes with patch_hash")
        return self


class CheckResult(Contract):
    verifier_name: Id
    verifier_version: Id
    required: bool
    passed: bool | None
    reason: CheckReason | None = None
    exit_code: int | None
    duration_ms: NonNegativeInt
    output_hash: Sha256 | None = None

    @model_validator(mode="after")
    def _reason_matches_result(self) -> Self:
        if self.passed is True and self.reason is not None:
            raise ValueError("a passing check has no failure reason")
        if self.passed is False and self.reason not in _FAILING_REASONS:
            raise ValueError("a failing check needs a failing reason")
        if self.passed is None and self.reason not in (
            CheckReason.TIMEOUT,
            CheckReason.UNAVAILABLE,
        ):
            raise ValueError("an inconclusive check needs reason timeout or unavailable")
        return self


def verification_status(checks: Iterable[CheckResult], required: Iterable[str]) -> ResultStatus:
    """Judge checks against the task's full plan, so a missing required check is never a pass."""
    by_name = {c.verifier_name: c.passed for c in checks}
    gates = [by_name.get(name) for name in ROUTER_CHECKS]
    results = [by_name.get(name) for name in required]
    if False in gates or False in results:
        return ResultStatus.FAILED
    if None in gates or not results or None in results:
        return ResultStatus.UNCERTAIN
    return ResultStatus.SUCCESS


def outcome_status(
    error_code: ErrorCode | None, checks: Iterable[CheckResult], required: Iterable[str]
) -> ResultStatus:
    if error_code in PROVIDER_ERRORS:
        return ResultStatus.UNCERTAIN
    if error_code is not None:
        return ResultStatus.FAILED
    return verification_status(checks, required)


class VerificationResult(Contract):
    required: tuple[Id, ...] = Field(description="Names of the task's required verifiers.")
    checks: tuple[CheckResult, ...] = Field(min_length=1)
    status: ResultStatus

    @model_validator(mode="after")
    def _status_matches_checks(self) -> Self:
        _require_unique((c.verifier_name for c in self.checks), "verifier name")
        for check in self.checks:
            expected = check.verifier_name in self.required or check.verifier_name in ROUTER_CHECKS
            if check.required != expected:
                raise ValueError(f"check {check.verifier_name} has the wrong required flag")
        require_status(self.status, verification_status(self.checks, self.required))
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

    @property
    def expected_cost_micro_usd(self) -> int | None:
        return next(c.expected_cost_micro_usd for c in self.candidates if c.model == self.selected)


class Attempt(Contract):
    attempt_id: Id
    parent_attempt_id: Id | None
    cause: AttemptCause
    started_at: AwareDatetime
    active_ms: NonNegativeInt = Field(description="Wall time for the worker and verification.")
    decision: DecisionReceipt
    context: ContextPacket
    result: ResultSummary
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
        if self.active_ms < self.result.latency_ms + sum(c.duration_ms for c in self.checks):
            raise ValueError("active_ms is shorter than the worker and checks it covers")
        require_status(self.status, outcome_status(self.result.error_code, self.checks, self.plan))
        return self

    @property
    def checks(self) -> tuple[CheckResult, ...]:
        return self.verification.checks if self.verification else ()

    @property
    def plan(self) -> tuple[str, ...]:
        return self.verification.required if self.verification else ()


class ExecutionBudget(Contract):
    max_attempts: PositiveInt = Field(description="Attempts that are not provider retries.")
    max_cost_micro_usd: NonNegativeInt
    max_active_ms: PositiveInt

    def within(self, limit: "ExecutionBudget") -> Self:
        for field in ("max_attempts", "max_cost_micro_usd", "max_active_ms"):
            if getattr(self, field) > getattr(limit, field):
                raise ValueError(f"{field} may lower the configured budget, not raise it")
        return self


class StopReason(StrEnum):
    ACCEPTED = "accepted"
    UNVERIFIED = "unverified"
    NO_STRONGER_MODEL = "no_stronger_model"
    PROVIDER_ERRORS = "provider_errors"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    COST_EXHAUSTED = "cost_exhausted"
    TIME_EXHAUSTED = "time_exhausted"


class StopReceipt(Contract):
    reason: StopReason
    detail: Id
    attempt_count: NonNegativeInt
    cost_micro_usd: NonNegativeInt
    active_ms: NonNegativeInt


class ExecutionTrace(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    trace_id: Id
    task: TaskSummary
    budget: ExecutionBudget
    attempts: tuple[Attempt, ...]
    stop: StopReceipt
    final_status: ResultStatus

    @model_validator(mode="after")
    def _valid_lineage(self) -> Self:
        _require_unique((a.attempt_id for a in self.attempts), "attempt_id")
        if self.attempts and self.attempts[0].cause != AttemptCause.INITIAL:
            raise ValueError("the first attempt must be the initial attempt")
        plan = required_checks(self.task.verifiers)
        earlier: dict[str, Attempt] = {}
        for attempt in self.attempts:
            if attempt.result.task_id != self.task.task_id:
                raise ValueError(f"attempt {attempt.attempt_id} ran a different task")
            if attempt.verification is not None and attempt.verification.required != plan:
                raise ValueError(f"attempt {attempt.attempt_id} skipped part of the check plan")
            if attempt.parent_attempt_id is not None:
                parent = earlier.get(attempt.parent_attempt_id)
                if parent is None:
                    raise ValueError(f"attempt {attempt.attempt_id} has no earlier parent")
                same_model = attempt.result.model == parent.result.model
                if attempt.cause == AttemptCause.ESCALATION and same_model:
                    raise ValueError(f"escalation {attempt.attempt_id} reused its parent's model")
                if attempt.cause == AttemptCause.RETRY and not same_model:
                    raise ValueError(f"retry {attempt.attempt_id} changed its parent's model")
            earlier[attempt.attempt_id] = attempt
        last = self.attempts[-1].status if self.attempts else ResultStatus.UNCERTAIN
        require_status(self.final_status, last)
        if (self.stop.reason == StopReason.ACCEPTED) != (last == ResultStatus.SUCCESS):
            raise ValueError("a trace stops as accepted exactly when its last attempt succeeded")
        if self.stop.attempt_count != len(self.attempts):
            raise ValueError("stop.attempt_count does not match the attempts")
        if self.stop.cost_micro_usd != sum(a.result.cost_micro_usd for a in self.attempts):
            raise ValueError("stop.cost_micro_usd does not match the attempts")
        if self.stop.active_ms < sum(a.active_ms for a in self.attempts):
            raise ValueError("stop.active_ms is shorter than the attempts it covers")
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
