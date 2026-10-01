import math
import tomllib
from decimal import Decimal
from pathlib import Path

from pydantic import Field

from model_router.contracts import Contract, Id, ModelRef, TokenUsage


class WorkerRole(Contract):
    name: Id
    instructions: Id
    max_turns: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    time_budget_s: float = Field(gt=0)
    code_mode: bool = True


class ModelPrice(Contract):
    """USD per million tokens. Uncached input excludes cache reads and writes."""

    input: Decimal = Field(ge=0)
    output: Decimal = Field(ge=0)
    cache_read: Decimal = Field(ge=0)
    cache_write: Decimal = Field(ge=0)


class UnpricedModelError(LookupError):
    pass


class PriceTable(Contract):
    version: Id
    models: dict[str, ModelPrice]

    def price_for(self, model: ModelRef) -> ModelPrice:
        key = f"{model.provider}:{model.model_id}"
        if key not in self.models:
            raise UnpricedModelError(f"no price for {key} in price table {self.version}")
        return self.models[key]

    def cost_micro_usd(self, model: ModelRef, usage: TokenUsage) -> int:
        price = self.price_for(model)
        uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
        # Tokens times USD per million tokens is exactly micro-USD.
        # Round up so cost is never understated.
        micro_usd = (
            uncached * price.input
            + usage.cache_read_tokens * price.cache_read
            + usage.cache_write_tokens * price.cache_write
            + usage.output_tokens * price.output
        )
        return math.ceil(micro_usd)


def load_roles(path: Path) -> dict[str, WorkerRole]:
    data = tomllib.loads(path.read_text())
    return {
        name: WorkerRole.model_validate({"name": name, **role})
        for name, role in data["roles"].items()
    }


def load_prices(path: Path) -> PriceTable:
    # Parse floats as Decimal so prices like 0.1 stay exact.
    return PriceTable.model_validate(tomllib.loads(path.read_text(), parse_float=Decimal))
