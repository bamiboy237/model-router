import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from model_router.contracts import SCHEMA_VERSION
from model_router.feedback import FeedbackEvent
from model_router.trial_record import TrialRecord

EXPORTED: dict[str, type[BaseModel]] = {
    f"trial_record.v{SCHEMA_VERSION}.json": TrialRecord,
    f"feedback_event.v{SCHEMA_VERSION}.json": FeedbackEvent,
}


def render(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write or check the exported JSON Schemas.")
    parser.add_argument("--dir", type=Path, default=Path("schemas"))
    parser.add_argument("--check", action="store_true", help="fail if a file is missing or stale")
    args = parser.parse_args(argv)

    stale = []
    for name, model in EXPORTED.items():
        path: Path = args.dir / name
        text = render(model)
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if stale:
        names = ", ".join(stale)
        print(f"stale schemas: {names}; run python -m model_router.schemas", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
