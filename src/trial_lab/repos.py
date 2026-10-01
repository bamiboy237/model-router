"""Task repositories as history-free snapshots.

A task's repository is one commit with no parents. A worker cannot read the upstream fix
or the commit that injected a bug from `git log`. The commit has fixed metadata, so the
same files always give the same base_sha.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

CACHE = Path(os.environ.get("MODEL_ROUTER_CACHE", "~/.cache/model-router")).expanduser()
_IGNORED = shutil.ignore_patterns(".DS_Store", "__pycache__", "node_modules", ".git")
# Hermetic git: the host's config, hooks, and global ignores must not change a snapshot.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "trial-lab",
    "GIT_AUTHOR_EMAIL": "trial-lab@invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "trial-lab",
    "GIT_COMMITTER_EMAIL": "trial-lab@invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
}


class RepoError(RuntimeError):
    pass


def mirror(url: str, sha: str) -> Path:
    """A local mirror of url that contains sha, cloned or fetched on first use."""
    name = url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
    path = CACHE / "repos" / f"{name}-{_digest(url)[:8]}.git"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--mirror", url, str(path))
    if not _has_commit(path, sha):
        _git("-C", str(path), "fetch", "--quiet", "origin", sha)
    return path


def snapshot_upstream(url: str, sha: str, setup_patch: str) -> tuple[Path, str]:
    source = mirror(url, sha)

    def fill(work: Path) -> None:
        _git("clone", "--quiet", "--no-checkout", str(source), str(work))
        _git("-C", str(work), "checkout", "--quiet", "--detach", sha)
        shutil.rmtree(work / ".git")

    return _snapshot(f"{url}@{sha}", setup_patch, fill)


def snapshot_fixture(source: Path, setup_patch: str) -> tuple[Path, str]:
    def fill(work: Path) -> None:
        shutil.copytree(source, work, ignore=_IGNORED)

    files = sorted(p for p in source.rglob("*") if p.is_file() and _kept(p, source))
    fingerprint = "".join(f"{p.relative_to(source)}:{_digest(p.read_bytes())}" for p in files)
    return _snapshot(f"fixture:{fingerprint}", setup_patch, fill)


def _snapshot(
    identity: str, setup_patch: str, fill: Callable[[Path], None]
) -> tuple[Path, str]:
    path = CACHE / "snapshots" / _digest(f"{identity}\n{setup_patch}")[:16]
    if path.exists():
        return path, _git("-C", str(path), "rev-parse", "HEAD").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        work = Path(tmp) / "repo"
        fill(work)
        _git("-C", str(work), "init", "--quiet", "--template=", "--initial-branch=main")
        if setup_patch:
            _git("-C", str(work), "apply", "-", stdin=setup_patch)
        _git("-C", str(work), "add", "--all", "--force")
        _git("-C", str(work), "commit", "--quiet", "--no-gpg-sign", "-m", "Task snapshot")
        work.rename(path)
    return path, _git("-C", str(path), "rev-parse", "HEAD").strip()


def _kept(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    return not any(p in {".DS_Store", "__pycache__", "node_modules", ".git"} for p in parts)


def _has_commit(repo: Path, sha: str) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
    )
    return probe.returncode == 0


def _git(*args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        input=stdin,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RepoError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _digest(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()
