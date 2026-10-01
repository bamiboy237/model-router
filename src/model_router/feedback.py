"""Feedback on attempts from humans and the orchestrator, and the evidence tally it feeds.

Events are append-only. A correction is a newer event from the same source; nothing is
rewritten. Events hold no free text, so they can be stored next to traces.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from model_router.contracts import (
    PROVIDER_ERRORS,
    SCHEMA_VERSION,
    Contract,
    Domain,
    Id,
    Kind,
    ModelRef,
    ResultStatus,
    Sha256,
)
from model_router.routing.config import RouterConfig, model_key, model_ref
from model_router.trial_record import TrialRecord


class Verdict(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class Aspect(StrEnum):
    VISUAL = "visual"
    LOGIC = "logic"
    SCOPE = "scope"
    STYLE = "style"
    OTHER = "other"


class FeedbackSource(StrEnum):
    HUMAN = "human"
    ORCHESTRATOR = "orchestrator"


class FeedbackEvent(Contract):
    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: Id
    trace_id: Id
    attempt_id: Id
    patch_hash: Sha256 | None = Field(description="The patch that was reviewed, if any.")
    source: FeedbackSource
    verdict: Verdict
    rating: Annotated[int, Field(ge=1, le=5)] | None = None
    aspect: Aspect | None = None
    occurred_at: AwareDatetime


class Evidence(Contract):
    """Weighted outcomes for one model on one tag, blended with the configured prior."""

    model: ModelRef
    tag: Id
    prior: float | None
    successes: float
    failures: float
    estimate: float | None


def report_outcome(
    *,
    record: TrialRecord,
    source: FeedbackSource,
    verdict: Verdict,
    rating: int | None = None,
    aspect: Aspect | None = None,
) -> FeedbackEvent:
    return FeedbackEvent(
        event_id=f"fb-{uuid4().hex}",
        trace_id=record.trace_id,
        attempt_id=record.attempt_id,
        patch_hash=record.patch_hash,
        source=source,
        verdict=verdict,
        rating=rating,
        aspect=aspect,
        occurred_at=datetime.now(UTC),
    )


def append_feedback(path: Path, event: FeedbackEvent) -> None:
    with path.open("a") as log:
        log.write(event.model_dump_json() + "\n")


def read_feedback(path: Path) -> tuple[FeedbackEvent, ...]:
    if not path.exists():
        return ()
    lines = path.read_text().splitlines()
    return tuple(FeedbackEvent.model_validate_json(line) for line in lines if line)


def tally(
    records: Iterable[TrialRecord], events: Iterable[FeedbackEvent], config: RouterConfig
) -> tuple[Evidence, ...]:
    """Count one weighted vote per attempt, grouped by model and the attempt's own tag.

    Votes, strongest first: failed required checks (always a failure, whatever the feedback
    says), the latest human verdict, the latest orchestrator verdict, then passing checks.
    Provider errors and attempts with no evidence cast no vote.
    """
    rows = {(r.trace_id, r.attempt_id): r for r in records}
    latest = _latest(events, rows)
    weights = {
        FeedbackSource.HUMAN: config.feedback.human,
        FeedbackSource.ORCHESTRATOR: config.feedback.orchestrator,
    }
    totals: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for _, record in sorted(rows.items()):
        vote = _vote(record, latest, weights, config.feedback.partial)
        if vote is None:
            continue
        success, weight = vote
        tag = f"{record.kind}/{record.domain}" if record.domain else str(record.kind)
        bucket = totals[(model_key(record.model), tag)]
        bucket[0] += success * weight
        bucket[1] += (1 - success) * weight
    return tuple(
        _evidence(model, tag, s, f, config) for (model, tag), (s, f) in sorted(totals.items())
    )


def _latest(
    events: Iterable[FeedbackEvent], rows: dict[tuple[str, str], TrialRecord]
) -> dict[tuple[str, str, FeedbackSource], FeedbackEvent]:
    seen: dict[str, FeedbackEvent] = {}
    latest: dict[tuple[str, str, FeedbackSource], FeedbackEvent] = {}
    for event in events:
        if event.event_id in seen:
            if seen[event.event_id] != event:
                raise ValueError(f"event {event.event_id} was recorded twice with different data")
            continue
        seen[event.event_id] = event
        record = rows.get((event.trace_id, event.attempt_id))
        if record is None:
            raise ValueError(f"event {event.event_id} names an unknown attempt")
        if event.patch_hash != record.patch_hash:
            raise ValueError(f"event {event.event_id} reviewed a different patch")
        slot = (event.trace_id, event.attempt_id, event.source)
        current = latest.get(slot)
        if current is None or (event.occurred_at, event.event_id) > (
            current.occurred_at,
            current.event_id,
        ):
            latest[slot] = event
    return latest


def _vote(
    record: TrialRecord,
    latest: dict[tuple[str, str, FeedbackSource], FeedbackEvent],
    weights: dict[FeedbackSource, float],
    partial: float,
) -> tuple[float, float] | None:
    if record.error_code in PROVIDER_ERRORS:
        return None
    if record.status == ResultStatus.FAILED:
        return 0.0, 1.0
    for source in (FeedbackSource.HUMAN, FeedbackSource.ORCHESTRATOR):
        event = latest.get((record.trace_id, record.attempt_id, source))
        if event is not None:
            value = {Verdict.SUCCESS: 1.0, Verdict.PARTIAL: partial, Verdict.FAILED: 0.0}
            return value[event.verdict], weights[source]
    if record.status == ResultStatus.SUCCESS:
        return 1.0, 1.0
    return None


def _evidence(
    model: str, tag: str, successes: float, failures: float, config: RouterConfig
) -> Evidence:
    kind, _, domain = tag.partition("/")
    spec = config.models.get(model)
    found = spec.prior(Kind(kind), Domain(domain) if domain else None) if spec else None
    prior = found[0] if found else None
    n = config.feedback.prior_strength
    if prior is not None:
        estimate: float | None = (prior * n + successes) / (n + successes + failures)
    elif successes + failures > 0:
        estimate = successes / (successes + failures)
    else:
        estimate = None
    return Evidence(
        model=model_ref(model),
        tag=tag,
        prior=prior,
        successes=successes,
        failures=failures,
        estimate=estimate,
    )
