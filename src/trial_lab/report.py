from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from model_router.contracts import ModelRef, ResultStatus
from model_router.routing import model_key, repick
from model_router.trial_record import LabInfo, TrialRecord

MIN_SAMPLES = 5


@dataclass(frozen=True)
class LabRecord:
    record: TrialRecord
    lab: LabInfo


def lab_records(records: Iterable[TrialRecord]) -> list[LabRecord]:
    rows = []
    for record in records:
        if record.lab is None:
            raise ValueError(f"trial {record.trace_id} was not written by trial_lab")
        rows.append(LabRecord(record, record.lab))
    return rows


@dataclass(frozen=True)
class Stats:
    trials: int
    successes: int
    cost_micro_usd: float
    latency_ms: float

    @classmethod
    def of(cls, rows: Sequence[LabRecord]) -> "Stats":
        return cls(
            trials=len(rows),
            successes=sum(r.record.status == ResultStatus.SUCCESS for r in rows),
            cost_micro_usd=sum(r.record.cost_micro_usd for r in rows) / len(rows),
            latency_ms=median(r.record.latency.total_ms for r in rows),
        )

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials


def report(
    rows: Sequence[LabRecord],
    *,
    error_count: int,
    error_cost_micro_usd: int,
    min_samples: int = MIN_SAMPLES,
) -> list[str]:
    if not rows:
        return ["no trials recorded"]
    labs = {(r.lab.run_id, r.lab.plan_hash, r.lab.harness_version) for r in rows}
    if len(labs) != 1:
        raise ValueError("a report covers one run of one plan and harness")
    ((run_id, plan_hash, harness),) = labs
    spent = sum(r.record.cost_micro_usd for r in rows)
    arms = sorted({r.lab.arm_id for r in rows})
    models = {r.lab.arm_id: r.record.model for r in rows}
    lines = [
        f"run {run_id}: plan {plan_hash[:12]}, harness {harness}, {len(rows)} trials, "
        f"${spent / 1e6:.4f}",
        f"provider errors: {error_count}, ${error_cost_micro_usd / 1e6:.4f} (not model evidence)",
        f"cells with fewer than {min_samples} trials show insufficient_evidence",
        "",
        "by arm",
    ]
    by_arm = _group(rows, lambda r: r.lab.arm_id)
    for arm in arms:
        lines.append(f"  {arm} ({model_key(models[arm])}): {_cell(by_arm[arm], min_samples)}")
    for title, key in (
        ("by arm and task kind", lambda r: str(r.record.kind)),
        ("by arm and family", lambda r: r.lab.task_family),
    ):
        lines += ["", title]
        for (arm, value), group in sorted(_group(rows, lambda r: (r.lab.arm_id, key(r))).items()):
            lines.append(f"  {arm}  {value}: {_cell(group, min_samples)}")
    lines += ["", "task difficulty (pass rate over every arm)"]
    by_task = _group(rows, lambda r: r.record.task_id)
    for task_id, group in sorted(by_task.items(), key=lambda item: Stats.of(item[1]).success_rate):
        first = group[0]
        per_arm = ", ".join(
            f"{arm} {s.successes}/{s.trials}"
            for arm, s in sorted((a, Stats.of(g)) for a, g in _group(group, _arm).items())
        )
        lines.append(
            f"  {task_id} ({first.lab.task_family}, {first.record.kind}): "
            f"{_rate(Stats.of(group), min_samples)}; {per_arm}"
        )
    lines += ["", "baselines (success averages tasks; cost is one try at every task)"]
    lines += [f"  {line}" for line in _baselines(rows, arms, models, by_task, min_samples)]
    return lines


def _baselines(
    rows: Sequence[LabRecord],
    arms: Sequence[str],
    models: Mapping[str, ModelRef],
    by_task: Mapping[str, list[LabRecord]],
    min_samples: int,
) -> list[str]:
    overall = {arm: Stats.of(group) for arm, group in _group(rows, _arm).items()}
    strongest = min(arms, key=lambda a: (-overall[a].success_rate, overall[a].cost_micro_usd, a))
    cheapest = min(arms, key=lambda a: (overall[a].cost_micro_usd, -overall[a].success_rate, a))
    fastest = min(arms, key=lambda a: (overall[a].latency_ms, -overall[a].success_rate, a))
    picks: list[tuple[str, Callable[[str], set[str]]]] = [
        (f"always strongest ({strongest})", lambda task_id: {strongest}),
        (f"always cheapest ({cheapest})", lambda task_id: {cheapest}),
        (f"lowest latency ({fastest})", lambda task_id: {fastest}),
    ]
    run_models = set(models.values())

    def rule_based(task_id: str) -> set[str]:
        chosen = repick(by_task[task_id][0].lab.router_receipt, run_models)
        return {arm for arm, model in models.items() if model == chosen}

    picks.append(("rule-based router (restricted to the run's models)", rule_based))
    lines = []
    for name, pick in picks:
        successes: list[float] = []
        costs: list[float] = []
        latencies: list[int] = []
        trials = 0
        for task_id, group in by_task.items():
            chosen = [r for r in group if r.lab.arm_id in pick(task_id)]
            if not chosen:
                continue
            stats = Stats.of(chosen)
            successes.append(stats.success_rate)
            costs.append(stats.cost_micro_usd)
            latencies += [r.record.latency.total_ms for r in chosen]
            trials += len(chosen)
        covered = f"{len(successes)}/{len(by_task)} tasks"
        if trials < min_samples:
            lines.append(f"{name}: {covered}, n={trials}, insufficient_evidence")
            continue
        lines.append(
            f"{name}: {covered}, n={trials}, success {sum(successes) / len(successes):.0%}, "
            f"${sum(costs) / 1e6:.4f}, p50 {median(latencies) / 1000:.1f}s"
        )
    return lines


def _arm(row: LabRecord) -> str:
    return row.lab.arm_id


def _group[K](rows: Iterable[LabRecord], key: Callable[[LabRecord], K]) -> dict[K, list[LabRecord]]:
    groups: dict[K, list[LabRecord]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


def _rate(stats: Stats, min_samples: int) -> str:
    if stats.trials < min_samples:
        return f"n={stats.trials}, insufficient_evidence"
    return f"n={stats.trials}, success {stats.success_rate:.0%}"


def _cell(rows: Sequence[LabRecord], min_samples: int) -> str:
    stats = Stats.of(rows)
    if stats.trials < min_samples:
        return _rate(stats, min_samples)
    return (
        f"{_rate(stats, min_samples)}, ${stats.cost_micro_usd / 1e6:.4f}/trial, "
        f"p50 {stats.latency_ms / 1000:.1f}s"
    )
