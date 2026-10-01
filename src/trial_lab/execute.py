import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from trial_lab.plan import Trial

ResultT = TypeVar("ResultT")
TrialRunner = Callable[[Trial], Awaitable[ResultT]]


class TrialError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Completed(Generic[ResultT]):
    trial: Trial
    result: ResultT


@dataclass(frozen=True)
class Failed:
    trial: Trial
    error_code: str


async def run_trials(
    trials: Sequence[Trial],
    runner: TrialRunner[ResultT],
    *,
    timeout_s: float,
) -> list[Completed[ResultT] | Failed]:
    outcomes: list[Completed[ResultT] | Failed] = []
    for trial in trials:
        try:
            async with asyncio.timeout(timeout_s):
                result = await runner(trial)
        except TimeoutError:
            outcomes.append(Failed(trial, "duration_limit_reached"))
        except TrialError as error:
            outcomes.append(Failed(trial, error.code))
        except Exception:
            outcomes.append(Failed(trial, "unexpected_trial_failure"))
        else:
            outcomes.append(Completed(trial, result))
    return outcomes
