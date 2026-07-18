"""Deterministic, credential-free collaborators for runtime tests."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class FakeClock:
    """A manually advanced UTC clock that never reads the system clock."""

    current: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))

    def now(self) -> datetime:
        return self.current

    def timestamp(self) -> float:
        return self.current.timestamp()

    def advance(self, seconds: float) -> datetime:
        self.current += timedelta(seconds=seconds)
        return self.current


@dataclass
class FakeIdGenerator:
    """A predictable opaque-ID source for assertions and replay fixtures."""

    prefix: str = "test"
    _sequence: int = 0

    def next(self) -> str:
        self._sequence += 1
        return f"{self.prefix}_{self._sequence:04d}"


@dataclass
class FakeProvider:
    """A scripted provider replacement that makes no network requests."""

    responses: Iterable[str] = ()
    prompts: list[str] = field(default_factory=list)
    _remaining: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self._remaining = list(self.responses)

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._remaining:
            raise RuntimeError("FakeProvider has no scripted response remaining")
        return self._remaining.pop(0)
