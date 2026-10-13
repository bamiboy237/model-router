"""A run directory: the plan it ran, append-only trial rows, provider errors, and artifacts.

runs/<run_id>/
    plan.toml       the plan file as given when the run started
    trials.jsonl    one TrialRecord per finished trial
    errors.jsonl    trials a provider error stopped; a resume runs them again
    artifacts/<trial_id>/
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from model_router.contracts import ErrorCode
from model_router.trial_record import TrialRecord


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.trials = root / "trials.jsonl"
        self.errors = root / "errors.jsonl"

    def records(self) -> list[TrialRecord]:
        return [TrialRecord.model_validate_json(line) for line in self._lines(self.trials)]

    def error_cost_micro_usd(self) -> int:
        return sum(int(json.loads(line)["cost_micro_usd"]) for line in self._lines(self.errors))

    def add_record(self, record: TrialRecord) -> None:
        _append(self.trials, record.model_dump_json())

    def add_error(self, trial_id: UUID, error_code: ErrorCode, cost_micro_usd: int) -> None:
        row = {
            "trial_id": str(trial_id),
            "error_code": str(error_code),
            "cost_micro_usd": cost_micro_usd,
            "at": datetime.now(UTC).isoformat(),
        }
        _append(self.errors, json.dumps(row))

    def artifacts(self, trial_id: UUID) -> Path:
        path = self.root / "artifacts" / str(trial_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            # A run killed mid-write leaves a partial last row. Drop it, so the trial runs
            # again and the next row does not join onto the fragment.
            with path.open("r+b") as file:
                file.truncate(data.rfind(b"\n") + 1)
            data = path.read_bytes()
        return [line for line in data.decode().splitlines() if line]


def _append(path: Path, line: str) -> None:
    with path.open("a") as file:
        file.write(line + "\n")
        file.flush()
        os.fsync(file.fileno())
