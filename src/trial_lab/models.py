from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage


class ModelRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["openai", "anthropic"]
    model_id: str
    base_url: str | None = None


def build_model(ref: ModelRef) -> Model:
    if ref.provider == "openai":
        if ref.base_url is not None:
            # Custom OpenAI-compatible endpoints speak chat completions only.
            return OpenAIChatModel(ref.model_id, provider=OpenAIProvider(base_url=ref.base_url))
        # The OpenAI API itself: use the modern Responses API. GPT-5.x models
        # reject function tools with reasoning on the legacy chat completions path.
        return OpenAIResponsesModel(ref.model_id, provider=OpenAIProvider())
    if ref.base_url is not None:
        return AnthropicModel(ref.model_id, provider=AnthropicProvider(base_url=ref.base_url))
    return AnthropicModel(ref.model_id)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: RunUsage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
