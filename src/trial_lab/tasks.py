"""Task corpus: tasks/<family>/<task_id>/ holds task.toml and its patches.

- setup.patch (optional) turns the upstream or fixture files into the task's starting point,
  for example by injecting a bug. It is part of the snapshot, so the worker cannot see it.
- reference.patch is a known-good solution.
- bad.patch (optional) is a plausible wrong solution.
- hidden_tests.patch (optional) is applied only when checking.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from model_router.contracts import (
    ContextRef,
    Contract,
    Domain,
    Id,
    Kind,
    TaskSpec,
    VerifierSpec,
    require_domain_matches_kind,
)
from trial_lab.repos import snapshot_fixture, snapshot_upstream

FIXTURES_DIR = "_repos"


class Upstream(Contract):
    url: Id
    sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class TaskFile(Contract):
    id: Id
    family: Id
    kind: Kind
    domain: Domain | None = None
    image: Id
    upstream: Upstream | None = None
    fixture: Id | None = Field(default=None, description=f"A directory in tasks/{FIXTURES_DIR}.")
    instruction: Id
    overview: str = ""
    files: tuple[Id, ...] = ()
    protected_paths: tuple[Id, ...] = ()
    verifiers: tuple[VerifierSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        require_domain_matches_kind(self.kind, self.domain)
        if (self.upstream is None) == (self.fixture is None):
            raise ValueError("a task needs exactly one of upstream or fixture")
        if not any(v.required for v in self.verifiers):
            raise ValueError("a task needs at least one required verifier")
        return self


@dataclass(frozen=True)
class LabTask:
    file: TaskFile
    root: Path
    setup_patch: str
    reference_patch: str
    bad_patch: str | None
    hidden_tests: str

    @property
    def task_id(self) -> str:
        return self.file.id

    def spec(self) -> TaskSpec:
        """Build the snapshot repository and the TaskSpec a worker and verifier use."""
        if self.file.upstream is not None:
            repo, sha = snapshot_upstream(
                self.file.upstream.url, self.file.upstream.sha, self.setup_patch
            )
        else:
            assert self.file.fixture is not None
            source = self.root / FIXTURES_DIR / self.file.fixture
            repo, sha = snapshot_fixture(source, self.setup_patch)
        return TaskSpec(
            task_id=self.file.id,
            kind=self.file.kind,
            domain=self.file.domain,
            overview=self.file.overview,
            instruction=self.file.instruction,
            repo=str(repo),
            base_sha=sha,
            context_refs=tuple(ContextRef(kind="file", path=p) for p in self.file.files),
            verifiers=self.file.verifiers,
            protected_paths=self.file.protected_paths,
            hidden_tests=self.hidden_tests,
        )


def load_tasks(root: Path) -> list[LabTask]:
    loaded = [load_task(path.parent, root) for path in sorted(root.glob("*/*/task.toml"))]
    tasks = [t for t in loaded if t is not None]
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            raise ValueError(f"duplicate task id {task.task_id}")
        seen.add(task.task_id)
    return tasks


def load_task(directory: Path, root: Path) -> LabTask | None:
    family = directory.parent.name
    if family == FIXTURES_DIR:
        return None
    try:
        file = TaskFile.model_validate(tomllib.loads((directory / "task.toml").read_text()))
    except ValueError as error:
        raise ValueError(f"{directory / 'task.toml'}: {error}") from error
    if (file.family, file.id) != (family, directory.name):
        raise ValueError(f"{directory} must hold task {family}/{directory.name}")
    return LabTask(
        file=file,
        root=root,
        setup_patch=_read(directory / "setup.patch") or "",
        reference_patch=_read(directory / "reference.patch") or _missing(directory, "reference"),
        bad_patch=_read(directory / "bad.patch"),
        hidden_tests=_read(directory / "hidden_tests.patch") or "",
    )


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _missing(directory: Path, name: str) -> str:
    raise ValueError(f"{directory} has no {name}.patch")
