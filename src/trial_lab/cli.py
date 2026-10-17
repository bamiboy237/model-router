import argparse
import asyncio
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from trial_lab.admission import admit_all
from trial_lab.export import HOLDOUT_FRACTION, SPLIT_SEED, export
from trial_lab.plan import load_plan
from trial_lab.report import MIN_SAMPLES, lab_records, report
from trial_lab.run import PreparedPlan, load_settings, prepare, run_plan
from trial_lab.store import RunStore
from trial_lab.tasks import LabTask, load_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab")
    parser.add_argument("--tasks", type=Path, default=Path("tasks"), help="task corpus root")
    parser.add_argument("--config", type=Path, default=Path("config"), help="router config dir")
    commands = parser.add_subparsers(dest="command", required=True)
    tasks = commands.add_parser("tasks").add_subparsers(dest="action", required=True)
    check = tasks.add_parser("check", help="validate task files and run admission")
    check.add_argument("ids", nargs="*", help="task ids to check; all tasks if none")
    check.add_argument("--jobs", type=int, default=4, help="tasks checked at once")
    plan = commands.add_parser("plan", help="print a plan's trials and estimated cost")
    plan.add_argument("plan", type=Path)
    run = commands.add_parser("run", help="run a plan, or resume a run with --run-id")
    run.add_argument("plan", type=Path)
    run.add_argument("--run-id", help="resume this run, or start it under this id")
    run.add_argument("--runs", type=Path, default=Path("runs"), help="runs directory")
    report = commands.add_parser("report", help="print a run's results and fixed baselines")
    report.add_argument("run_id")
    report.add_argument("--runs", type=Path, default=Path("runs"), help="runs directory")
    report.add_argument(
        "--min-samples", type=int, default=MIN_SAMPLES, help="trials a cell needs for rates"
    )
    export = commands.add_parser("export", help="write training and holdout datasets")
    export.add_argument("run_ids", nargs="+")
    export.add_argument("--out", type=Path, required=True, help="new dataset directory")
    export.add_argument("--runs", type=Path, default=Path("runs"), help="runs directory")
    export.add_argument("--seed", default=SPLIT_SEED, help="family split seed")
    export.add_argument("--holdout-fraction", type=float, default=HOLDOUT_FRACTION)
    args = parser.parse_args(argv)
    if args.command == "report":
        return _report(args.runs / args.run_id, args.min_samples)
    if args.command == "export":
        return _export(args.runs, args.run_ids, args.out, args.seed, args.holdout_fraction)
    try:
        corpus = load_tasks(args.tasks)
    except ValueError as error:  # includes TOML and validation errors
        print(f"invalid task corpus: {error}", file=sys.stderr)
        return 2
    if args.command == "tasks":
        return _tasks_check(corpus, args.ids, args.jobs)
    try:
        prepared = prepare(load_plan(args.plan), corpus, load_settings(args.config))
    except (ValueError, OSError) as error:
        print(f"invalid plan: {error}", file=sys.stderr)
        return 2
    if args.command == "plan":
        _print_plan(prepared)
        return 0
    return _run(prepared, args.plan, corpus, args.runs, args.run_id)


def _report(root: Path, min_samples: int) -> int:
    if not root.is_dir():
        print(f"no run at {root}", file=sys.stderr)
        return 2
    store = RunStore(root)
    try:
        lines = report(
            lab_records(store.records()),
            error_count=store.error_count(),
            error_cost_micro_usd=store.error_cost_micro_usd(),
            min_samples=min_samples,
        )
    except ValueError as error:
        print(f"cannot report {root.name}: {error}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


def _export(runs: Path, run_ids: list[str], out: Path, seed: str, fraction: float) -> int:
    if len(set(run_ids)) != len(run_ids):
        print("a run is listed twice", file=sys.stderr)
        return 2
    missing = [run_id for run_id in run_ids if not (runs / run_id).is_dir()]
    if missing:
        print(f"no run at {', '.join(str(runs / m) for m in missing)}", file=sys.stderr)
        return 2
    try:
        rows = [row for run_id in run_ids for row in lab_records(RunStore(runs / run_id).records())]
        manifest = export(rows, out, seed=seed, holdout_fraction=fraction)
    except ValueError as error:
        print(f"cannot export: {error}", file=sys.stderr)
        return 2
    for name, side in (("train", manifest["train"]), ("holdout", manifest["holdout"])):
        print(f"{name}: {side['trials']} trials, families {', '.join(side['families'])}")
    print(f"wrote {out}")
    return 0


def _tasks_check(corpus: list[LabTask], ids: list[str], jobs: int) -> int:
    unknown = set(ids) - {t.task_id for t in corpus}
    if unknown:
        print(f"unknown task ids: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    selected = [t for t in corpus if not ids or t.task_id in ids]
    return _admit(selected, jobs)


def _admit(selected: list[LabTask], jobs: int) -> int:
    admissions = asyncio.run(admit_all(selected, jobs=jobs))
    for admission in admissions:
        if admission.admitted:
            print(f"admitted  {admission.task_id}")
        else:
            print(f"rejected  {admission.task_id}")
            for problem in admission.problems:
                print("  " + problem.replace("\n", "\n    "))
    rejected = sum(not a.admitted for a in admissions)
    print(f"{len(admissions) - rejected} admitted, {rejected} rejected")
    return 1 if rejected else 0


def _print_plan(prepared: PreparedPlan) -> None:
    plan, file = prepared.plan, prepared.file
    print(
        f"plan {plan.plan_id} ({plan.plan_hash[:12]}): {len(plan.task_ids)} tasks x "
        f"{len(plan.arms)} arms x {plan.repetitions} repetitions = {len(prepared.trials)} trials"
    )
    for arm in plan.arms:
        cost = sum(prepared.estimates[t.task_id, t.arm_id] for t in prepared.trials
                   if t.arm_id == arm.arm_id)
        model = f"{arm.model.provider}:{arm.model.model_id}"
        print(
            f"  {arm.arm_id}  {model}  thinking={arm.thinking or 'default'}  "
            f"code_mode={'on' if arm.code_mode else 'off'}  ${cost / 1e6:.2f}"
        )
    print(
        f"estimated cost ${prepared.estimate_micro_usd / 1e6:.2f} from the router's usage "
        f"guesses; prices {file.prices}; concurrency {file.concurrency}"
    )


def _run(
    prepared: PreparedPlan, plan_path: Path, corpus: list[LabTask], runs: Path, run_id: str | None
) -> int:
    plan = prepared.plan
    run_id = run_id or f"{plan.plan_id}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    root = runs / run_id
    if root.exists():
        try:
            started = load_plan(root / "plan.toml").resolve(corpus)
        except (ValueError, OSError) as error:
            print(f"cannot resume {run_id}: {error}", file=sys.stderr)
            return 2
        if started.plan_hash != plan.plan_hash:
            print(f"cannot resume {run_id}: it ran a different plan or task set", file=sys.stderr)
            return 2
        print(f"resuming {root}")
    _print_plan(prepared)
    print("checking task admission")
    if _admit([t.task for t in prepared.tasks.values()], jobs=4):
        print("a task failed admission; fix it or drop it from the plan", file=sys.stderr)
        return 2
    if not root.exists():
        root.mkdir(parents=True)
        shutil.copyfile(plan_path, root / "plan.toml")
        print(f"started {root}")
    store = RunStore(root)
    summary = asyncio.run(run_plan(prepared, store, run_id=run_id))
    left = len(prepared.trials) - summary.skipped - summary.recorded
    print(
        f"{summary.recorded} recorded, {summary.skipped} already recorded, {left} pending, "
        f"{summary.provider_errors} provider errors; spent ${summary.spent_micro_usd / 1e6:.4f}"
    )
    if summary.stopped:
        print(f"stopped: {summary.stopped}", file=sys.stderr)
    if left:
        print(f"resume with: lab run {plan_path} --run-id {run_id}")
    return 1 if summary.failure or left else 0


if __name__ == "__main__":
    sys.exit(main())
