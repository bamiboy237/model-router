import os
import re
import shlex
import time
from dataclasses import dataclass

import httpx
from pydantic_ai import Agent, AgentRunResult, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings, ThinkingEffort
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import WorkspaceBackend
from pydantic_ai_harness import (
    ClearToolResults,
    CodeMode,
    FileSystem,
    RepoContext,
    Shell,
    SubAgents,
    SystemReminders,
    ToolOutputLimits,
    WarnNearLimits,
)
from pydantic_ai_harness.coder import FILE_TOOL_NAMES
from pydantic_ai_harness.filesystem import FileSystemToolset
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.tool_output_limits import Band, Truncate

from model_router.contracts import (
    TEST_SETUP_PATHS,
    ContextPacket,
    ErrorCode,
    ModelRef,
    TaskResult,
    TaskSpec,
    TokenUsage,
)
from model_router.workers.config import PriceTable, WorkerRole
from model_router.workers.sandbox import (
    DockerSandbox,
    DockerWorkspace,
    SandboxConfig,
    open_sandbox,
)

# Bump on any change to the worker's tools, prompt, or reminders, and on any
# pydantic-ai-harness upgrade, so trials from different harnesses are never pooled.
HARNESS_VERSION = "5"
# Lookups worth batching in one run_code call. Edits, checks, and shell commands stay
# direct tool calls, so every change to the checkout is its own visible step.
CODE_MODE_TOOLS = ("read_file", "list_files", "grep")
# Replaces Coder's built-in instructions, which a caller can only add to. Those ask the model
# to seek approval, run extra lint and type checks, and poll long-running work, and each
# costs turns in a headless trial. Some models are also trained to stop and ask, and a
# question ends the trial because no one answers.
_WORKER_INSTRUCTIONS = """\
You work alone in a sandboxed checkout of a repository. Read the code, make the change, and \
verify it with the tools.
No one will answer questions during this task. Do not ask for input or confirmation. Make \
reasonable assumptions, finish the task, and name the assumptions in your summary.
Follow the repository's instructions and conventions. Fix causes, not symptoms. Leave only the \
requested change, and delete any scratch files you create.
When tool calls do not depend on each other, make them in the same response.
Read code with read_file, grep, and list_files, not with cat, grep, or ls in run_command. Read \
whole files, and grep large ones.
Do not repeat a call that already gave you what you need.
run_command waits for the command to finish and returns its output. Pass timeout_seconds for a \
command that takes longer than 30 seconds. Nothing runs in the background.
Do not delegate work you can finish yourself in a few steps."""
# Per-provider additions, keyed by ModelRef.provider. Gemini 3 asks for short, direct
# prompts, and Gemini 3 Flash has been reported to return one function call per response.
_PROVIDER_GUIDANCE = {
    "google": "You can return several function calls in one response, and they run at the "
    "same time.",
}
CHECKS_TOOL = "run_checks"
_CHECKS_PASSED = "PASS"
_CHECK_OUTPUT_TAIL = 4000
# Coder's limits: a read stays under the output cap, and a stale edit or denied path is
# corrected from its error rather than ending the run on the second mistake.
_MAX_READ_CHARS = 50_000
_MAX_OUTPUT_CHARS = 64_000
_MAX_FILE_TOOL_RETRIES = 5

_CONTEXT_OVERFLOW = re.compile(
    r"context.?length|context window|maximum context|input token count|too many tokens", re.I
)
_ERROR_MESSAGE_LIMIT = 500


@dataclass(frozen=True)
class WorkerDeps:
    sandbox: DockerSandbox
    task: TaskSpec


class _UnlimitedRequests(AbstractCapability[WorkerDeps]):
    async def wrap_run(
        self, ctx: RunContext[WorkerDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[str]:
        # Every fresh run, including a delegate, otherwise gets the library's 50-request cap.
        if ctx.usage_limits is not None:
            ctx.usage_limits.request_limit = None
        return await handler()


class _BoundToolOutputs(ToolOutputLimits[WorkerDeps]):
    def get_toolset(self) -> None:
        # Truncation only, so the spill-retrieval tool would never have anything to read.
        return None


def build_model(ref: ModelRef) -> Model:
    if ref.provider == "openai":
        return OpenAIResponsesModel(ref.model_id, provider=OpenAIProvider())
    if ref.provider == "google":
        return GoogleModel(ref.model_id, provider=GoogleProvider())
    if ref.provider == "meta":
        return OpenAIResponsesModel(
            ref.model_id,
            provider=OpenAIProvider(
                base_url="https://api.meta.ai/v1",
                api_key=os.environ["MODEL_API_KEY"],
            ),
            # Meta requires encrypted reasoning replay and commentary phases in tool loops.
            profile=OpenAIModelProfile(
                supports_thinking=True,
                thinking_always_enabled=True,
                thinking_enabled_by_default=True,
                openai_supports_reasoning=True,
                openai_supports_reasoning_effort_none=False,
                openai_supports_encrypted_reasoning_content=True,
                openai_supports_phase=True,
                openai_responses_requires_store_false=True,
            ),
        )
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
    note: str | None = None,
    thinking: ThinkingEffort | None = None,
    code_mode: bool = False,
) -> TaskResult:
    """Run one agent loop on a task in a fresh sandbox and return its patch or error.

    Pass model to replace the provider with a scripted pydantic_ai FunctionModel or TestModel.
    Pass note to tell the worker why an earlier attempt at the task failed.
    Pass thinking to set the reasoning effort; None keeps the model's default.
    Pass code_mode to let the worker batch lookups in one run_code call.
    """
    prices.price_for(model_ref)
    agent = build_agent(
        model if model is not None else build_model(model_ref),
        role,
        provider=model_ref.provider,
        thinking=thinking,
        code_mode=code_mode,
    )
    usage = RunUsage()
    transcript = b""
    patch: str | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None

    async with open_sandbox(task, sandbox_config or SandboxConfig()) as sandbox:
        started = time.monotonic()
        workspace = DockerWorkspace(sandbox)
        prompt = _prompt(task, context, note, await _read_listed_files(context, workspace))
        try:
            async with agent.iter(
                prompt,
                deps=WorkerDeps(sandbox, task),
                workspace=workspace,
            ) as run:
                try:
                    async for _ in run:
                        pass
                finally:
                    usage = run.usage
                    transcript = run.all_messages_json()
        except Exception as exc:
            error_code = classify_error(exc)
            if error_code is None:
                raise
            error_message = str(exc)[:_ERROR_MESSAGE_LIMIT]
        latency_ms = int((time.monotonic() - started) * 1000)
        if error_code is None:
            patch = await sandbox.diff()

    tokens = _tokens(usage)
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
        transcript=transcript.decode(),
    )


def build_agent(
    model: Model,
    role: WorkerRole,
    *,
    provider: str,
    thinking: ThinkingEffort | None = None,
    code_mode: bool = False,
) -> Agent[WorkerDeps, str]:
    """The worker agent: Coder's capabilities, with its own instructions and run_command.

    It differs from Coder in two ways. Coder's instructions are replaced, not extended. Coder's
    `shell` starts each command as a detached job that outlives the sandbox's per-command
    deadline and returns process handles to poll, so commands go through `run_command`, which
    waits under the deadline and returns the output.
    """
    instructions = f"{role.instructions}\n\n{_WORKER_INSTRUCTIONS}"
    if provider in _PROVIDER_GUIDANCE:
        instructions += "\n" + _PROVIDER_GUIDANCE[provider]
    if code_mode:
        instructions += (
            "\nWhen you need several files or searches, fetch them together in one run_code call."
        )
    capabilities: list[AbstractCapability[WorkerDeps]] = [
        _UnlimitedRequests(),
        _file_system(),
        Shell[WorkerDeps](tools=["run_command"], denied_commands=[]),
        RepoContext[WorkerDeps](expose_inventory_tool=False),
        SubAgents[WorkerDeps](include_self=True, agent_folders=None),
        ClearToolResults[WorkerDeps](max_fraction=0.7),
        WarnNearLimits[WorkerDeps](max_context_fraction=0.9),
        _BoundToolOutputs(
            bands=[Band(over=_MAX_OUTPUT_CHARS, action=Truncate(max_chars=_MAX_OUTPUT_CHARS))]
        ),
        RepairToolArguments[WorkerDeps](),
        SystemReminders(dynamic_reminders=[_checks_passed_reminder]),
    ]
    if code_mode:
        capabilities.append(CodeMode(tools=list(CODE_MODE_TOOLS)))
    settings: ModelSettings | None = {"thinking": thinking} if thinking is not None else None
    return Agent(
        model,
        deps_type=WorkerDeps,
        instructions=[instructions, _project_dir],
        capabilities=capabilities,
        toolsets=[FunctionToolset([run_checks])],
        model_settings=settings,
    )


def _file_system() -> FileSystem[WorkerDeps]:
    # Coder's file tools, without content hashes: one writer per checkout needs no
    # optimistic locking, and the hashes add tokens to every read and write.
    return FileSystem[WorkerDeps](
        content_hashes=False,
        max_read_chars=_MAX_READ_CHARS,
        tools=FILE_TOOL_NAMES,
        max_retries=_MAX_FILE_TOOL_RETRIES,
    )


async def _project_dir(ctx: RunContext[WorkerDeps]) -> str:
    return (
        f"Your project is `{await ctx.workspace.working_dir()}`. Commands start there, and the "
        "file tools only accept paths inside it."
    )


async def _read_listed_files(
    context: ContextPacket, workspace: WorkspaceBackend
) -> list[tuple[str, str]]:
    """Each listed file as read_file returns it, so the first request needs no read round."""
    tools = _file_system().get_toolset()
    if not isinstance(tools, FileSystemToolset):
        raise TypeError("the worker's file tools are read-write, so their toolset is unfiltered")
    return [
        (ref.path, await tools.read_file(ref.path, workspace=workspace))
        for ref in context.refs
        if ref.kind == "file"
    ]


async def run_checks(ctx: RunContext[WorkerDeps]) -> str:
    """Run the task's checks exactly as the grader runs them. Takes no arguments.

    Returns PASS when every check passes, or FAIL with the end of each failing check's output.
    """
    task, sandbox = ctx.deps.task, ctx.deps.sandbox
    if not task.verifiers:
        return "This task has no automated checks. Check your change with an inline script."
    failed: list[str] = []
    for verifier in task.verifiers:
        result = await sandbox.run(shlex.join(verifier.command), verifier.timeout_s)
        if result.exit_code == 0:
            continue
        status = "timed out" if result.timed_out else f"exit code {result.exit_code}"
        failed.append(f"{verifier.name}: {status}\n{result.output[-_CHECK_OUTPUT_TAIL:]}")
    names = ", ".join(v.name for v in task.verifiers)
    if failed:
        return "FAIL\n" + "\n\n".join(failed)
    # The grader adds hidden tests, so a pass here is the visible bar, not the final result.
    return f"{_CHECKS_PASSED}: {names}"


def _checks_passed_reminder(ctx: RunContext[WorkerDeps]) -> str | None:
    # Reminders are evaluated before each model request and never stored, so reading the
    # newest request fires this exactly once per passing run_checks call.
    last = ctx.messages[-1] if ctx.messages else None
    if not isinstance(last, ModelRequest):
        return None
    for part in last.parts:
        if (
            isinstance(part, ToolReturnPart)
            and part.tool_name == CHECKS_TOOL
            and str(part.content).startswith(_CHECKS_PASSED)
        ):
            return (
                "<system-reminder>\nThe checks pass. Reply with your summary now unless the "
                "task needs more.\n</system-reminder>"
            )
    return None


def _tokens(usage: RunUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
    )


def _prompt(
    task: TaskSpec, context: ContextPacket, note: str | None, files: list[tuple[str, str]]
) -> str:
    lines = [f"Background: {task.overview}", ""] if task.overview else []
    lines += [task.instruction, ""]
    if context.refs:
        lines.append("Start with these files: " + ", ".join(ref.path for ref in context.refs))
    if files:
        lines += ["", "The listed files, as read_file returns them:"]
        for path, text in files:
            lines += ["", f'<file path="{path}">', text, "</file>"]
    # Gemini's prompting guide puts instructions after long context, so the workflow
    # follows the file contents.
    step_one = "1. Read the code the task needs."
    if files:
        step_one = (
            "1. The listed files are above, so do not read them again. "
            "Read any other code the task needs."
        )
    lines += [
        "",
        "Work in this order:",
        step_one,
        "2. Make the smallest change that completes the task.",
    ]
    if task.verifiers:
        commands = "; ".join(shlex.join(v.command) for v in task.verifiers)
        lines += [
            f"3. Call {CHECKS_TOOL}(). It runs the task's checks: {commands}. "
            "Fix any failure your change causes, then call it again.",
            f"4. When {CHECKS_TOOL}() passes, reply with your summary and stop. Call it again "
            "only if you change code after it passes.",
        ]
    else:
        lines += [
            "3. Check your change with an inline script.",
            "4. Reply with your summary and stop.",
        ]
    lines += [
        "",
        "Do not read git history, check tool versions, or benchmark code unless the task asks "
        "for it. Add tests only if the task asks for them.",
    ]
    setup = ", ".join(p for p in TEST_SETUP_PATHS if not p.startswith("*/"))
    lines.append(f"Do not add or change test setup files, in any directory: {setup}.")
    if task.protected_paths:
        lines.append("Do not change these paths: " + ", ".join(task.protected_paths) + ".")
    lines.append("A change to a protected file fails the check.")
    if note:
        lines += ["", "An earlier attempt failed. You start from a clean checkout.", note]
    lines.append("Your summary is one paragraph describing your change.")
    return "\n".join(lines)
