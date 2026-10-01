import shlex
import time
from dataclasses import dataclass
from fnmatch import fnmatchcase

from model_router.contracts import (
    PATCH_APPLIES,
    PROTECTED_PATHS,
    CheckReason,
    CheckResult,
    ResultStatus,
    TaskSpec,
    VerificationResult,
    VerifierSpec,
    required_checks,
    sha256_text,
    verification_status,
)
from model_router.workers.sandbox import (
    CommandResult,
    DockerSandbox,
    SandboxConfig,
    open_sandbox,
)

ROUTER_CHECK_VERSION = "1"
NOTE_OUTPUT_CHARS = 2_000
# sh exits 126 when it cannot run the command and 127 when it cannot find it.
_UNAVAILABLE_EXIT_CODES = frozenset({126, 127})


@dataclass(frozen=True)
class Verification:
    result: VerificationResult
    # What failed and the end of its output, for the next attempt's prompt. Never stored.
    note: str


async def verify(task: TaskSpec, patch: str, config: SandboxConfig | None = None) -> Verification:
    """Apply a patch to a fresh checkout of base_sha and run every verifier on it."""
    async with open_sandbox(task, config or SandboxConfig()) as sandbox:
        applied, changed, apply_ms = await _apply(sandbox, patch)
        checks = [_gate(PATCH_APPLIES, applied, CheckReason.PATCH_CONFLICT, apply_ms)]
        notes = [] if applied else ["The patch does not apply cleanly to the base commit."]
        if applied:
            touched = [path for path in changed if _protected(path, task.protected_paths)]
            checks.append(_gate(PROTECTED_PATHS, not touched, CheckReason.PROTECTED_PATH, 0))
            if touched:
                notes.append("The patch changed protected files: " + ", ".join(touched))
            else:
                for spec in task.verifiers:
                    run = await sandbox.run(shlex.join(spec.command), spec.timeout_s)
                    check = _check(spec, run)
                    checks.append(check)
                    if check.passed is not True:
                        notes.append(_note(spec, check, run))
    required = required_checks(task.verifiers)
    status = verification_status(checks, required)
    result = VerificationResult(required=required, checks=tuple(checks), status=status)
    return Verification(result, "\n\n".join(notes) if status != ResultStatus.SUCCESS else "")


async def _apply(sandbox: DockerSandbox, patch: str) -> tuple[bool, list[str], int]:
    if not patch:
        return True, [], 0
    started = time.monotonic()
    # Not --index: the clone's index carries host file stats, which never match in the container.
    applied = await sandbox.run("git apply - && git add -A", 60, stdin=patch.encode())
    elapsed = int((time.monotonic() - started) * 1000)
    if applied.exit_code != 0:
        return False, [], elapsed
    # --no-renames lists both sides of a rename, so moving a protected file counts as changing it.
    names = await sandbox.run(
        f"git diff --cached --name-only --no-renames {sandbox.base_sha}", 60, limit=None
    )
    return True, names.output.split("\n") if names.output else [], elapsed


def _protected(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatchcase(path, p) or path.startswith(p.rstrip("/") + "/") for p in patterns)


def _gate(name: str, passed: bool, reason: CheckReason, duration_ms: int) -> CheckResult:
    return CheckResult(
        verifier_name=name,
        verifier_version=ROUTER_CHECK_VERSION,
        required=True,
        passed=passed,
        reason=None if passed else reason,
        exit_code=None,
        duration_ms=duration_ms,
    )


def _check(spec: VerifierSpec, run: CommandResult) -> CheckResult:
    passed: bool | None
    if run.timed_out:
        passed, reason = None, CheckReason.TIMEOUT
    elif run.exit_code in _UNAVAILABLE_EXIT_CODES:
        passed, reason = None, CheckReason.UNAVAILABLE
    elif run.exit_code == 0:
        passed, reason = True, None
    else:
        passed, reason = False, CheckReason.ASSERTION_FAILED
    return CheckResult(
        verifier_name=spec.name,
        verifier_version=spec.version,
        required=spec.required,
        passed=passed,
        reason=reason,
        exit_code=run.exit_code,
        duration_ms=run.duration_ms,
        output_hash=sha256_text(run.output),
    )


def _note(spec: VerifierSpec, check: CheckResult, run: CommandResult) -> str:
    tail = run.output[-NOTE_OUTPUT_CHARS:]
    return f"Check {spec.name} ({shlex.join(spec.command)}) {check.reason}:\n{tail}"
