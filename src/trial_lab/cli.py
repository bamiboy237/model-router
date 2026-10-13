import argparse
import asyncio
import sys
from pathlib import Path

from trial_lab.admission import admit_all
from trial_lab.tasks import load_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lab")
    commands = parser.add_subparsers(dest="command", required=True)
    tasks = commands.add_parser("tasks").add_subparsers(dest="action", required=True)
    check = tasks.add_parser("check", help="validate task files and run admission")
    check.add_argument("ids", nargs="*", help="task ids to check; all tasks if none")
    check.add_argument("--tasks", type=Path, default=Path("tasks"), help="task corpus root")
    check.add_argument("--jobs", type=int, default=4, help="tasks checked at once")
    args = parser.parse_args(argv)
    return _tasks_check(args.tasks, args.ids, args.jobs)


def _tasks_check(root: Path, ids: list[str], jobs: int) -> int:
    try:
        corpus = load_tasks(root)
    except ValueError as error:  # includes TOML and validation errors
        print(f"invalid task corpus: {error}", file=sys.stderr)
        return 2
    unknown = set(ids) - {t.task_id for t in corpus}
    if unknown:
        print(f"unknown task ids: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    selected = [t for t in corpus if not ids or t.task_id in ids]
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


if __name__ == "__main__":
    sys.exit(main())
