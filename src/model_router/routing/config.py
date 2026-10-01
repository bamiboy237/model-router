import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from model_router.contracts import (
    Contract,
    Domain,
    ExecutionBudget,
    Id,
    Kind,
    ModelRef,
    NonNegativeInt,
    PositiveInt,
)

PickRule = Literal["cheapest_above", "best_success", "best_value"]
Probability = Annotated[float, Field(ge=0, le=1)]
ANY_TAG = "*"


class UsageEstimate(Contract):
    """Tokens a typical job of one kind spends, on top of the linked files."""

    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt


class ModelSpec(Contract):
    context_limit: int = Field(ge=1)
    tool_support: bool = True
    success: dict[str, Probability]

    @model_validator(mode="after")
    def _valid_success_keys(self) -> Self:
        for key in self.success:
            if not _valid_tag_key(key):
                raise ValueError(f"success key {key!r} must be '*', '<kind>', or '<kind>/<domain>'")
        return self

    def prior(self, kind: Kind, domain: Domain | None) -> tuple[float, str] | None:
        """The most specific success guess for a tag, and the key it came from."""
        for key in tag_keys(kind, domain):
            if key in self.success:
                return self.success[key], key
        return None


class EscalationConfig(Contract):
    tries_per_model: PositiveInt
    provider_retries: NonNegativeInt
    provider_backoff_s: float = Field(ge=0)
    budget: ExecutionBudget


class FeedbackConfig(Contract):
    """How much each source of feedback counts, in attempts."""

    prior_strength: float = Field(gt=0)
    human: float = Field(ge=0)
    orchestrator: float = Field(ge=0)
    partial: Probability


class RouterConfig(Contract):
    policy_version: Id
    pick_rule: PickRule
    min_success: Probability = 0.8
    roles: dict[Kind, Id]
    usage: dict[Kind, UsageEstimate]
    models: dict[str, ModelSpec]
    escalation: EscalationConfig
    feedback: FeedbackConfig

    @model_validator(mode="after")
    def _complete(self) -> Self:
        for label, table in (("roles", self.roles), ("usage", self.usage)):
            missing = set(Kind) - set(table)
            if missing:
                raise ValueError(f"{label} has no entry for {', '.join(sorted(missing))}")
        for key in self.models:
            model_ref(key)
        return self


def model_ref(key: str) -> ModelRef:
    provider, sep, model_id = key.partition(":")
    if not sep:
        raise ValueError(f"model key {key!r} must be 'provider:model_id'")
    return ModelRef(provider=provider, model_id=model_id)


def model_key(ref: ModelRef) -> str:
    return f"{ref.provider}:{ref.model_id}"


def tag_keys(kind: Kind, domain: Domain | None) -> tuple[str, ...]:
    """Prior keys from most to least specific."""
    specific = (f"{kind}/{domain}",) if domain is not None else ()
    return (*specific, str(kind), ANY_TAG)


def load_router_config(path: Path) -> RouterConfig:
    return RouterConfig.model_validate(tomllib.loads(path.read_text()))


def _valid_tag_key(key: str) -> bool:
    if key == ANY_TAG:
        return True
    kind, _, domain = key.partition("/")
    return kind in set(Kind) and (not domain or domain in set(Domain))
