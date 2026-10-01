import random
from typing import Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trial_lab.hashing import content_hash
from trial_lab.models import ModelRef

TRIAL_NAMESPACE = UUID("d5dc6ec7-e058-4a64-bf55-e4dbe9c546af")


class Arm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    model: ModelRef
    context_strategy: str


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    task_ids: tuple[str, ...]
    arms: tuple[Arm, ...]
    repetitions: int = Field(default=1, ge=1)
    seed: int

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if not self.task_ids or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task IDs must be non-empty and unique")
        arm_ids = [arm.arm_id for arm in self.arms]
        if not arm_ids or len(set(arm_ids)) != len(arm_ids):
            raise ValueError("arm IDs must be non-empty and unique")
        return self


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
    plan_hash = content_hash(plan)
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
