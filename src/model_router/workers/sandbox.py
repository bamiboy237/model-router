import asyncio
import os
import re
import shlex
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field
from pydantic_ai.workspaces import CommandResult as WorkspaceCommandResult
from pydantic_ai.workspaces import (
    WorkspaceCommand,
    WorkspaceRef,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from model_router.contracts import Contract, Id, TaskSpec

WORKDIR = "/work"
OUTPUT_LIMIT = 20_000
# GNU timeout exits 124 when it stops the command and 137 when it has to kill it.
_TIMEOUT_EXIT_CODES = frozenset({124, 137})
_CONTAINER_GONE = re.compile(r"Error response from daemon: (No such container|.* is not running)")


class SandboxError(RuntimeError):
    pass


class SandboxConfig(Contract):
    image: Id = "python:3.12"
    memory: Id = "2g"
    cpus: float = Field(default=2, gt=0)
    pids_limit: int = Field(default=512, ge=1)
    # The container exits on its own after this, so a killed host process cannot leave it
    # running forever. Worker loops have no separate time cap.
    lifetime_s: int = Field(default=7200, ge=1)


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
        code, output, _ = await _exec(argv, stdin=stdin, timeout_s=timeout_s + 15)
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


@dataclass(frozen=True)
class DockerWorkspace:
    """A sandbox as a pydantic_ai workspace backend, so harness file and shell tools run in it.

    File operations have no native API here; pydantic_ai derives them from run().
    """

    sandbox: DockerSandbox

    @property
    def ref(self) -> WorkspaceRef:
        return WorkspaceRef(provider="docker", id=self.sandbox.container_id)

    async def working_dir(self) -> str:
        return WORKDIR

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> WorkspaceCommandResult:
        if shell != isinstance(command, str):
            raise TypeError("pass a string command with shell=True and an argv sequence without")
        argv = ["docker", "exec"]
        for name, value in (env or {}).items():
            argv += ["--env", f"{name}={value}"]
        argv.append(self.sandbox.container_id)
        if timeout is not None:
            argv += ["timeout", "-k", "5", str(timeout)]
        argv += ["sh", "-c", command] if isinstance(command, str) else list(command)
        started = time.monotonic()
        code, stdout, stderr = await _exec(
            argv, stdin=None, timeout_s=None if timeout is None else timeout + 15, merge=False
        )
        if (
            timeout is not None
            and code in _TIMEOUT_EXIT_CODES
            and time.monotonic() - started >= timeout
        ):
            raise WorkspaceTimeoutError(
                f"command timed out after {timeout}s", stdout=stdout, stderr=stderr
            )
        if code != 0 and _CONTAINER_GONE.search(stderr):
            raise WorkspaceUnavailableError(stderr.strip())
        return WorkspaceCommandResult(exit_code=code, stdout=stdout, stderr=stderr)


@asynccontextmanager
async def open_sandbox(task: TaskSpec, config: SandboxConfig) -> AsyncIterator[DockerSandbox]:
    host_dir = Path(tempfile.mkdtemp(prefix="model-router-"))
    try:
        await _host("git", "clone", "--quiet", "--no-checkout", task.repo, str(host_dir))
        await _host("git", "-C", str(host_dir), "checkout", "--quiet", "--detach", task.base_sha)
        container_id = await _host(
            "docker", "run", "--detach", "--rm",
            "--label", "model-router.sandbox=1",
            "--network", "none",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/tmp",
            # Keep caches out of the checkout, so they never show up in a patch.
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTEST_ADDOPTS=-p no:cacheprovider",
            "--memory", config.memory,
            "--cpus", str(config.cpus),
            "--pids-limit", str(config.pids_limit),
            "--volume", f"{host_dir}:{WORKDIR}",
            "--workdir", WORKDIR,
            config.image, "sleep", str(config.lifetime_s),
        )
        try:
            yield DockerSandbox(container_id.strip(), task.base_sha)
        finally:
            await _host("docker", "rm", "--force", container_id.strip())
    finally:
        shutil.rmtree(host_dir, ignore_errors=True)


async def _host(*argv: str) -> str:
    code, output, _ = await _exec(list(argv), stdin=None, timeout_s=300)
    if code != 0:
        raise SandboxError(f"{argv[0]} {argv[1]} failed: {output.strip()}")
    return output


async def _exec(
    argv: list[str], *, stdin: bytes | None, timeout_s: float | None, merge: bool = True
) -> tuple[int, str, str]:
    """Run argv on the host. With merge, stderr is folded into the returned stdout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT if merge else asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise SandboxError(f"{argv[0]} {argv[1]} did not return within {timeout_s}s") from None
    assert proc.returncode is not None
    return proc.returncode, out.decode(errors="replace"), (err or b"").decode(errors="replace")


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters omitted ...]\n{text[-half:]}"
