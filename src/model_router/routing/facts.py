import math
import subprocess
from collections import Counter
from pathlib import PurePosixPath

from model_router.contracts import Contract, Id, NonNegativeInt
from model_router.routing.request import DelegationRequest

# Rough average for code across current tokenizers. Good enough to rule out models
# whose context window is far too small; not a billing number.
CHARS_PER_TOKEN = 4

_LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".swift": "swift", ".sql": "sql", ".css": "css", ".scss": "css", ".html": "html",
    ".vue": "vue", ".svelte": "svelte", ".sh": "shell", ".tf": "terraform",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".json": "json", ".md": "markdown",
}


class TaskFacts(Contract):
    file_count: NonNegativeInt
    context_tokens: NonNegativeInt
    language: Id


def measure(request: DelegationRequest) -> TaskFacts:
    """Measure the linked files at base_sha. Raises if a file does not exist there."""
    tokens_by_language: Counter[str] = Counter()
    for path in request.files:
        text = _read_at(request.repo, request.base_sha, path)
        tokens_by_language[_language(path)] += math.ceil(len(text) / CHARS_PER_TOKEN)
    known = Counter({lang: n for lang, n in tokens_by_language.items() if lang != "unknown"})
    language = known.most_common(1)[0][0] if known else "unknown"
    return TaskFacts(
        file_count=len(request.files),
        context_tokens=sum(tokens_by_language.values()),
        language=language,
    )


def _read_at(repo: str, sha: str, path: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, "show", f"{sha}:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"{path} does not exist at {sha[:12]} in {repo}")
    return result.stdout.decode(errors="replace")


def _language(path: str) -> str:
    name = PurePosixPath(path).name
    if name == "Dockerfile":
        return "dockerfile"
    return _LANGUAGES.get(PurePosixPath(path).suffix.lower(), "unknown")
