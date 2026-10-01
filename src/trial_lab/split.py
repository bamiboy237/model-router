from collections.abc import Mapping
from hashlib import sha256


def split_by_family(
    families: Mapping[str, str],
    *,
    seed: str,
    holdout_fraction: float,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between zero and one")
    train: list[str] = []
    holdout: list[str] = []
    for item_id, family in sorted(families.items()):
        digest = sha256(f"{seed}:{family}".encode()).digest()
        score = int.from_bytes(digest[:8], "big") / 2**64
        target = holdout if score < holdout_fraction else train
        target.append(item_id)
    return tuple(train), tuple(holdout)
