import hashlib
import json
from typing import Self

from pydantic import Field, model_validator

from model_router.contracts import (
    ContextPacket,
    ContextRef,
    Contract,
    Domain,
    Id,
    Kind,
    TaskSpec,
    VerifierSpec,
    require_domain_matches_kind,
)


class DelegationRequest(Contract):
    """A job handed to the router by a larger model."""

    repo: Id
    base_sha: str = Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")
    kind: Kind
    domain: Domain | None = None
    overview: str = ""
    task: Id
    files: tuple[Id, ...] = ()
    checks: tuple[VerifierSpec, ...] = ()
    protected_paths: tuple[Id, ...] = ()

    @model_validator(mode="after")
    def _valid_tags(self) -> Self:
        require_domain_matches_kind(self.kind, self.domain)
        return self

    @property
    def task_id(self) -> str:
        # Identical requests get the same id, so repeated delegations stay comparable.
        body = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return "task-" + hashlib.sha256(body.encode()).hexdigest()[:16]

    def to_task(self) -> TaskSpec:
        return TaskSpec(
            task_id=self.task_id,
            kind=self.kind,
            domain=self.domain,
            overview=self.overview,
            instruction=self.task,
            repo=self.repo,
            base_sha=self.base_sha,
            context_refs=self._refs(),
            verifiers=self.checks,
            protected_paths=self.protected_paths,
        )

    def to_context(self, context_tokens: int) -> ContextPacket:
        return ContextPacket(
            packet_id=f"{self.task_id}:caller_files",
            task_id=self.task_id,
            strategy="caller_files",
            refs=self._refs(),
            token_estimate=context_tokens,
        )

    def _refs(self) -> tuple[ContextRef, ...]:
        return tuple(ContextRef(kind="file", path=path) for path in self.files)
