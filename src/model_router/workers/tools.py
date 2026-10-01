import shlex

from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from model_router.workers.sandbox import DockerSandbox

MAX_COMMAND_TIMEOUT_S = 600
CODE_MODE_METADATA = {"code_mode": True}


async def list_files(ctx: RunContext[DockerSandbox], path: str = ".") -> str:
    """List files under a directory, skipping .git. Paths are relative to the repository root."""
    command = f"find {shlex.quote(path)} -path '*/.git' -prune -o -type f -print | sort | head -500"
    return (await ctx.deps.run(command, 30)).output


async def read_file(
    ctx: RunContext[DockerSandbox], path: str, start_line: int = 1, end_line: int | None = None
) -> str:
    """Read a file with line numbers. Optionally read only lines start_line to end_line."""
    end = "$" if end_line is None else str(end_line)
    command = f"cat -n -- {shlex.quote(path)} | sed -n '{int(start_line)},{end}p'"
    result = await ctx.deps.run(command, 30)
    return result.output if result.exit_code == 0 else f"error: {result.output}"


async def search(ctx: RunContext[DockerSandbox], pattern: str, path: str = ".") -> str:
    """Search file contents with a regular expression. Returns matching lines as path:line:text."""
    command = (
        f"grep -rnE --exclude-dir=.git -e {shlex.quote(pattern)} -- {shlex.quote(path)} | head -200"
    )
    return (await ctx.deps.run(command, 60)).output or "no matches"


async def write_file(ctx: RunContext[DockerSandbox], path: str, content: str) -> str:
    """Create or overwrite a file with the given content."""
    await ctx.deps.write(path, content)
    return f"wrote {path}"


async def edit_file(ctx: RunContext[DockerSandbox], path: str, old: str, new: str) -> str:
    """Replace one exact occurrence of old with new in a file. old must appear exactly once."""
    text = await ctx.deps.read(path)
    if text is None:
        return f"error: cannot read {path}"
    count = text.count(old)
    if count != 1:
        return f"error: old text appears {count} times in {path}; it must appear exactly once"
    await ctx.deps.write(path, text.replace(old, new))
    return f"edited {path}"


async def run_command(ctx: RunContext[DockerSandbox], command: str, timeout_s: int = 120) -> str:
    """Run a shell command in the repository root, such as the task's tests. There is no network."""
    timeout = max(1, min(timeout_s, MAX_COMMAND_TIMEOUT_S))
    result = await ctx.deps.run(command, timeout)
    status = "timed out" if result.timed_out else f"exit code {result.exit_code}"
    return f"{status}\n{result.output}"


def worker_toolsets() -> list[AbstractToolset[DockerSandbox]]:
    file_tools = FunctionToolset([list_files, read_file, search, write_file, edit_file])
    return [file_tools.with_metadata(**CODE_MODE_METADATA), FunctionToolset([run_command])]
