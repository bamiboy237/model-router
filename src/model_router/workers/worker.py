import asyncio
import re
import time

import httpx
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_ai_harness import CodeMode

from model_router.contracts import (
    ContextPacket,
    ErrorCode,
    ModelRef,
    TaskResult,
    TaskSpec,
    TokenUsage,
)
from model_router.workers.config import PriceTable, WorkerRole
from model_router.workers.sandbox import WORKDIR, DockerSandbox, SandboxConfig, open_sandbox
from model_router.workers.tools import CODE_MODE_METADATA, worker_toolsets

_CONTEXT_OVERFLOW = re.compile(
    r"context.?length|context window|maximum context|input token count|too many tokens", re.I
)
_ERROR_MESSAGE_LIMIT = 500


def build_model(ref: ModelRef) -> Model:
    if ref.provider == "openai":
        return OpenAIResponsesModel(ref.model_id, provider=OpenAIProvider())
    if ref.provider == "google":
        return GoogleModel(ref.model_id, provider=GoogleProvider())
    raise ValueError(f"unsupported provider {ref.provider!r}")


def classify_error(exc: BaseException) -> ErrorCode | None:
    """Map a run failure to an error code, or None for a setup mistake that must not be recorded."""
    if isinstance(exc, UsageLimitExceeded):
        return ErrorCode.BUDGET_EXCEEDED
    if isinstance(exc, TimeoutError):
        return ErrorCode.TIME_BUDGET_EXCEEDED
    if isinstance(exc, ContentFilterError):
        return ErrorCode.REFUSED
    if isinstance(exc, UnexpectedModelBehavior):
        return ErrorCode.INVALID_OUTPUT
    if isinstance(exc, ModelHTTPError):
        if exc.status_code == 429:
            return ErrorCode.RATE_LIMITED
        if exc.status_code >= 500:
            return ErrorCode.PROVIDER_UNAVAILABLE
        if exc.status_code in (400, 413) and _CONTEXT_OVERFLOW.search(str(exc.body)):
            return ErrorCode.CONTEXT_TOO_LONG
        return None
    if isinstance(exc, ModelAPIError | httpx.TransportError):
        return ErrorCode.NETWORK_ERROR
    return None


async def run_worker(
    *,
    task: TaskSpec,
    context: ContextPacket,
    role: WorkerRole,
    model_ref: ModelRef,
    attempt_id: str,
    prices: PriceTable,
    sandbox_config: SandboxConfig | None = None,
    model: Model | None = None,
) -> TaskResult:
    """Run one agent loop on a task in a fresh sandbox and return its patch or error.

    Pass model to replace the provider with a scripted pydantic_ai FunctionModel or TestModel.
    """
    prices.price_for(model_ref)
    capabilities: list[AbstractCapability[DockerSandbox]] = (
        [CodeMode(tools=CODE_MODE_METADATA)] if role.code_mode else []
    )
    agent = Agent(
        model or build_model(model_ref),
        deps_type=DockerSandbox,
        instructions=role.instructions,
        toolsets=worker_toolsets(),
        capabilities=capabilities,
    )
    limits = UsageLimits(request_limit=role.max_turns, total_tokens_limit=role.max_total_tokens)
    usage = RunUsage()
    patch: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None

    async with open_sandbox(task, sandbox_config or SandboxConfig()) as sandbox:
        started = time.monotonic()
        prompt = _prompt(task, context)
        try:
            async with asyncio.timeout(role.time_budget_s):
                async with agent.iter(prompt, deps=sandbox, usage_limits=limits) as run:
                    try:
                        async for _ in run:
                            pass
                    finally:
                        usage = run.usage
        except Exception as exc:
            error_code = classify_error(exc)
            if error_code is None:
                raise
            error_message = str(exc)[:_ERROR_MESSAGE_LIMIT]
        latency_ms = int((time.monotonic() - started) * 1000)
        if error_code is None:
            patch = await sandbox.diff()

    tokens = TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )
    return TaskResult(
        task_id=task.task_id,
        attempt_id=attempt_id,
        model=model_ref,
        patch=patch,
        error_code=error_code,
        error_message=error_message,
        usage=tokens,
        cost_micro_usd=prices.cost_micro_usd(model_ref, tokens),
        latency_ms=latency_ms,
    )


def _prompt(task: TaskSpec, context: ContextPacket) -> str:
    lines = [f"Background: {task.overview}", ""] if task.overview else []
    lines += [
        task.instruction,
        "",
        f"The repository is checked out at {WORKDIR}. Edit files there directly.",
    ]
    if context.refs:
        lines.append("Start with these files: " + ", ".join(ref.path for ref in context.refs))
    if task.verifiers:
        lines.append("The result will be checked with:")
        lines += [f"- {' '.join(v.command)}" for v in task.verifiers]
    lines.append("When you are done, reply with a one-paragraph summary of your change.")
    return "\n".join(lines)
