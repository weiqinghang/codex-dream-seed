from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MigrationStep:
    from_version: int
    to_version: int
    migration_id: str
    apply: Callable[[Path, dict[str, Any]], dict[str, Any]]

    def __post_init__(self) -> None:
        if self.to_version != self.from_version + 1:
            raise ValueError("registered migrations must connect adjacent schema versions")


_REGISTRY: dict[tuple[int, int], MigrationStep] = {}


def register(step: MigrationStep) -> None:
    key = (step.from_version, step.to_version)
    if key in _REGISTRY:
        raise ValueError(f"duplicate migration step: {key}")
    _REGISTRY[key] = step


def plan_migration(from_version: int, to_version: int) -> list[MigrationStep]:
    if from_version > to_version:
        raise MigrationError("down migrations are not supported; restore the pre-migration snapshot")
    steps: list[MigrationStep] = []
    current = from_version
    while current < to_version:
        key = (current, current + 1)
        step = _REGISTRY.get(key)
        if step is None:
            raise MigrationError(f"no adjacent migration registered for {current} -> {current + 1}")
        steps.append(step)
        current += 1
    return steps

