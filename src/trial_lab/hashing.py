import json
from collections.abc import Mapping
from hashlib import sha256

from pydantic import BaseModel


def canonical_json(value: BaseModel | Mapping[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(value: BaseModel | Mapping[str, object]) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()
