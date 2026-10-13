import random
import tomllib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai.settings import ThinkingEffort

from model_router.contracts import ModelRef
from trial_lab.hashing import content_hash
from trial_lab.tasks import LabTask

TRIAL_NAMESPACE = UUID("d5dc6ec7-e058-4a64-bf55-e4dbe9c546af")


class Arm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    model: ModelRef
    # task_files: the worker is pointed at the files the task lists.
    context_strategy: Literal["task_files"] = "task_files"
    thinking: ThinkingEffort | None = None


class Plan(BaseModel):
    """What a run does. Its hash is in every trial ID, so budget and concurrency stay out."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    task_ids: tuple[str, ...]
    arms: tuple[Arm, ...]
    repetitions: int = Field(default=1, ge=1)
    seed: int
    assignment: Literal["all_arms"] = "all_arms"

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.task_ids or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task IDs must be non-empty and unique")
        arm_ids = [arm.arm_id for arm in self.arms]
        if not arm_ids or len(set(arm_ids)) != len(arm_ids):
            raise ValueError("arm IDs must be non-empty and unique")
        return self

    @property
    def plan_hash(self) -> str:
        return content_hash(self)


class PlanFile(BaseModel):
    """plan.toml. Selects tasks by id or family; with neither, it takes every task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    seed: int
    repetitions: int = Field(default=1, ge=1)
    assignment: Literal["all_arms"] = "all_arms"
    tasks: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    arms: tuple[Arm, ...]
    max_usd: Decimal = Field(gt=0)
    concurrency: int = Field(default=2, ge=1)
    prices: str = Field(min_length=1, description="The price table version the plan expects.")

    def resolve(self, corpus: Sequence[LabTask]) -> Plan:
        by_id = {t.task_id: t for t in corpus}
        unknown = [t for t in self.tasks if t not in by_id]
        unknown += [f for f in self.families if f not in {t.file.family for t in corpus}]
        if unknown:
            raise ValueError("unknown tasks or families: " + ", ".join(unknown))
        selected = [
            t.task_id
            for t in corpus
            if (not self.tasks and not self.families)
            or t.task_id in self.tasks
            or t.file.family in self.families
        ]
        return Plan(
            plan_id=self.plan_id,
            task_ids=tuple(sorted(selected)),
            arms=self.arms,
            repetitions=self.repetitions,
            seed=self.seed,
            assignment=self.assignment,
        )


def load_plan(path: Path) -> PlanFile:
    try:
        return PlanFile.model_validate(tomllib.loads(path.read_text(), parse_float=Decimal))
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


class Trial(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: UUID
    task_id: str
    arm_id: str
    repetition: int
    ordinal: int


def build_trials(plan: Plan) -> tuple[Trial, ...]:
    blocks = [
        (task_id, repetition)
        for task_id in sorted(plan.task_ids)
        for repetition in range(1, plan.repetitions + 1)
    ]
    randomizer = random.Random(plan.seed)
    randomizer.shuffle(blocks)
    plan_hash = plan.plan_hash
    trials: list[Trial] = []
    for task_id, repetition in blocks:
        arms = sorted(plan.arms, key=lambda arm: arm.arm_id)
        randomizer.shuffle(arms)
        for arm in arms:
            trials.append(Trial(
                trial_id=uuid5(TRIAL_NAMESPACE, f"{plan_hash}:{task_id}:{arm.arm_id}:{repetition}"),
                task_id=task_id,
                arm_id=arm.arm_id,
                repetition=repetition,
                ordinal=len(trials) + 1,
            ))
    return tuple(trials)
