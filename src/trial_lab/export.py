"""Training and holdout datasets, split by task family.

out/
    train.jsonl     trial records from training families
    holdout.jsonl   trial records from holdout families
    manifest.json   runs, harness, split seed and fraction, families, and file hashes
"""

import json
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

from model_router.contracts import SCHEMA_VERSION
from trial_lab.report import LabRecord
from trial_lab.split import split_by_family

# A family's side depends only on the seed and its name, so adding families never moves an
# existing one across the split.
SPLIT_SEED = "split-v1"
HOLDOUT_FRACTION = 0.33


class Side(TypedDict):
    families: list[str]
    task_ids: list[str]
    trials: int
    sha256: str


class Manifest(TypedDict):
    schema_version: int
    harness_version: str
    runs: list[dict[str, str]]
    split: dict[str, str | float]
    train: Side
    holdout: Side


def export(
    rows: Sequence[LabRecord],
    out: Path,
    *,
    seed: str = SPLIT_SEED,
    holdout_fraction: float = HOLDOUT_FRACTION,
) -> Manifest:
    if out.exists():
        raise ValueError(f"{out} exists; export to a new directory")
    if not rows:
        raise ValueError("no trials to export")
    harnesses = {r.lab.harness_version for r in rows}
    if len(harnesses) != 1:
        raise ValueError(f"runs mix harness versions {', '.join(sorted(harnesses))}")
    families: dict[str, str] = {}
    for row in rows:
        family = families.setdefault(row.record.task_id, row.lab.task_family)
        if family != row.lab.task_family:
            raise ValueError(
                f"task {row.record.task_id} is in families {family} and {row.lab.task_family}"
            )
    train_ids, holdout_ids = split_by_family(families, seed=seed, holdout_fraction=holdout_fraction)
    if not train_ids or not holdout_ids:
        raise ValueError(f"seed {seed!r} puts every family on one side; choose another seed")
    runs = sorted({(r.lab.run_id, r.lab.plan_hash) for r in rows})
    out.mkdir(parents=True)

    def write(name: str, task_ids: tuple[str, ...]) -> Side:
        chosen = sorted(
            (r for r in rows if r.record.task_id in task_ids),
            key=lambda r: (r.lab.run_id, str(r.lab.trial_id)),
        )
        data = "".join(r.record.model_dump_json() + "\n" for r in chosen).encode()
        (out / f"{name}.jsonl").write_bytes(data)
        return {
            "families": sorted({families[t] for t in task_ids}),
            "task_ids": list(task_ids),
            "trials": len(chosen),
            "sha256": sha256(data).hexdigest(),
        }

    manifest: Manifest = {
        "schema_version": SCHEMA_VERSION,
        "harness_version": harnesses.pop(),
        "runs": [{"run_id": run_id, "plan_hash": plan_hash} for run_id, plan_hash in runs],
        "split": {"by": "family", "seed": seed, "holdout_fraction": holdout_fraction},
        "train": write("train", train_ids),
        "holdout": write("holdout", holdout_ids),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
