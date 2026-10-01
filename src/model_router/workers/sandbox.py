import asyncio
import os
import shlex
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field

from model_router.contracts import Contract, Id, TaskSpec

WORKDIR = "/work"
OUTPUT_LIMIT = 20_000
# GNU timeout exits 124 when it stops the command and 137 when it has to kill it.
_TIMEOUT_EXIT_CODES = frozenset({124, 137})


class SandboxError(RuntimeError):
    pass


class SandboxConfig(Contract):
    image: Id = "python:3.12"
    memory: Id = "2g"
    cpus: float = Field(default=2, gt=0)
    pids_limit: int = Field(default=512, ge=1)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    output: str
    duration_ms: int

    @property
    def timed_out(self) -> bool:
        return self.exit_code is None


@dataclass(frozen=True)
class DockerSandbox:
    container_id: str
    base_sha: str

    async def run(
        self,
        command: str,
        timeout_s: float,
        *,
        stdin: bytes | None = None,
        limit: int | None = OUTPUT_LIMIT,
    ) -> CommandResult:
        argv = ["docker", "exec"]
        if stdin is not None:
            argv.append("--interactive")
        # Killing the docker client does not stop the process inside the container,
        # so the deadline is enforced in the container and the host waits a little longer.
        argv += [self.container_id, "timeout", "-k", "5", str(timeout_s), "sh", "-c", command]
        started = time.monotonic()
        code, output = await _exec(argv, stdin=stdin, timeout_s=timeout_s + 15)
        elapsed = int((time.monotonic() - started) * 1000)
        exit_code = None if code in _TIMEOUT_EXIT_CODES else code
        return CommandResult(exit_code, _truncate(output, limit), elapsed)

    async def read(self, path: str) -> str | None:
        result = await self.run(f"cat -- {shlex.quote(path)}", 30, limit=None)
        return result.output if result.exit_code == 0 else None

    async def write(self, path: str, content: str) -> None:
        quoted = shlex.quote(path)
        command = f'mkdir -p -- "$(dirname -- {quoted})" && cat > {quoted}'
        result = await self.run(command, 30, stdin=content.encode())
        if result.exit_code != 0:
            raise SandboxError(f"write {path} failed: {result.output}")

    async def diff(self) -> str:
        command = f"git add -A && git diff --cached --binary {self.base_sha} 2>/dev/null"
        result = await self.run(command, 60, limit=None)
        if result.exit_code != 0:
            raise SandboxError(f"git diff failed with exit code {result.exit_code}")
        return result.output


@asynccontextmanager
async def open_sandbox(task: TaskSpec, config: SandboxConfig) -> AsyncIterator[DockerSandbox]:
    host_dir = Path(tempfile.mkdtemp(prefix="model-router-"))
    try:
        await _host("git", "clone", "--quiet", "--no-checkout", task.repo, str(host_dir))
        await _host("git", "-C", str(host_dir), "checkout", "--quiet", "--detach", task.base_sha)
        container_id = await _host(
            "docker", "run", "--detach", "--rm",
            "--network", "none",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/tmp",
            "--memory", config.memory,
            "--cpus", str(config.cpus),
            "--pids-limit", str(config.pids_limit),
            "--volume", f"{host_dir}:{WORKDIR}",
            "--workdir", WORKDIR,
            config.image, "sleep", "infinity",
        )
        try:
            yield DockerSandbox(container_id.strip(), task.base_sha)
        finally:
            await _host("docker", "rm", "--force", container_id.strip())
    finally:
        shutil.rmtree(host_dir, ignore_errors=True)


async def _host(*argv: str) -> str:
    code, output = await _exec(list(argv), stdin=None, timeout_s=300)
    if code != 0:
        raise SandboxError(f"{argv[0]} {argv[1]} failed: {output.strip()}")
    return output


async def _exec(argv: list[str], *, stdin: bytes | None, timeout_s: float) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise SandboxError(f"{argv[0]} {argv[1]} did not return within {timeout_s}s") from None
    assert proc.returncode is not None
    return proc.returncode, out.decode(errors="replace")


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters omitted ...]\n{text[-half:]}"
