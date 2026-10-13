"""Admission: a task enters a plan only if its verifiers tell good work from bad.

1. The reference patch passes every required verifier.
2. The empty patch fails at least one required task verifier.
3. The bad patch, if present, applies cleanly and fails at least one required task verifier.

Without these checks, a broken verifier turns into a wrong training label.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from model_router.contracts import PATCH_APPLIES, PROTECTED_PATHS, ROUTER_CHECKS, ResultStatus
from model_router.verification import Verification, verify
from model_router.workers.sandbox import SandboxConfig, SandboxError
from trial_lab.repos import RepoError
from trial_lab.tasks import LabTask


@dataclass(frozen=True)
class Admission:
    task_id: str
    problems: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return not self.problems


async def admit_all(tasks: Sequence[LabTask], *, jobs: int = 4) -> list[Admission]:
    limit = asyncio.Semaphore(jobs)

    async def one(task: LabTask) -> Admission:
        async with limit:
            return await admit(task)

    return list(await asyncio.gather(*(one(t) for t in tasks)))


async def admit(task: LabTask) -> Admission:
    try:
        spec = task.spec()
    except RepoError as error:
        return Admission(task.task_id, (f"snapshot: {error}",))
    missing = [r.path for r in spec.context_refs if not (Path(spec.repo) / r.path).exists()]
    if missing:
        return Admission(task.task_id, ("files not in snapshot: " + ", ".join(missing),))
    config = SandboxConfig(image=task.file.image)
    problems: list[str] = []
    patches = {"reference": task.reference_patch, "empty": ""}
    if task.bad_patch is not None:
        patches["bad"] = task.bad_patch
    for name, patch in patches.items():
        try:
            verification = await verify(spec, patch, config)
        except SandboxError as error:
            problems.append(f"{name} patch: {error}")
            continue
        problem = _check(name, verification)
        if problem:
            problems.append(problem)
    return Admission(task.task_id, tuple(problems))


def _check(name: str, verification: Verification) -> str | None:
    result = verification.result
    if name == "reference":
        if result.status == ResultStatus.SUCCESS:
            return None
        return f"reference patch is {result.status}:\n{verification.note}"
    gates = {c.verifier_name: c.passed for c in result.checks if c.verifier_name in ROUTER_CHECKS}
    if gates.get(PATCH_APPLIES) is False:
        return f"{name} patch does not apply"
    if gates.get(PROTECTED_PATHS) is False:
        return f"{name} patch changes protected paths, so it tests the gate, not the verifiers"
    failed = any(
        c.required and c.passed is False and c.verifier_name not in ROUTER_CHECKS
        for c in result.checks
    )
    return None if failed else f"{name} patch fails no required verifier"
