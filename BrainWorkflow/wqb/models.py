from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlphaCandidate:
    expression: str
    settings: dict[str, Any]
    generation: int
    parent_hash: str | None = None
    action: str = "seed"
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComplexityResult:
    ok: bool
    operator_count: int
    field_count: int
    operators: dict[str, int]
    fields: set[str]
    reasons: list[str]


@dataclass(frozen=True)
class CheckItem:
    name: str
    result: str
    value: Any = None
    limit: Any = None


@dataclass(frozen=True)
class CheckSummary:
    alpha_id: str
    hard_pass: bool
    failed: list[CheckItem]
    warnings: list[CheckItem]
    pending: list[CheckItem]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class OptimizationAction:
    parent_hash: str
    reason: str
    action_type: str
    details: dict[str, Any]
