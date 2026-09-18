"""
core/harness.py - PRE-BUILT.
Test execution, timing and coverage collection. Thin utility used by
run.py and eval/score.py so timing/coverage bookkeeping lives in one
place instead of being reinvented per entry point.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class TimedResult:
    value: object
    elapsed_ms: int


def timed(fn: Callable[..., T], *args, **kwargs) -> TimedResult:
    t0 = time.time()
    value = fn(*args, **kwargs)
    return TimedResult(value=value, elapsed_ms=int((time.time() - t0) * 1000))


@dataclass
class CoverageStats:
    total_rules: int = 0
    validated: int = 0
    invalidated: int = 0
    uncoverable: int = 0
    untested: int = 0
    counted_ids: set = field(default_factory=set)

    def add(self, rule_id: str, status: str):
        if rule_id in self.counted_ids:
            return
        self.counted_ids.add(rule_id)
        self.total_rules += 1
        if status == "VALIDATED":
            self.validated += 1
        elif status.startswith("INVALIDATED"):
            self.invalidated += 1
        elif status == "UNCOVERABLE":
            self.uncoverable += 1
        else:
            self.untested += 1

    def as_dict(self) -> dict:
        return {
            "total_rules": self.total_rules,
            "validated": self.validated,
            "invalidated": self.invalidated,
            "uncoverable": self.uncoverable,
            "untested": self.untested,
            "coverage_pct": round(100 * (self.total_rules - self.untested) / self.total_rules, 1)
            if self.total_rules else 0.0,
        }


def coverage_from_matrix(rows) -> CoverageStats:
    stats = CoverageStats()
    for row in rows:
        stats.add(row.rule_id, row.status)
    return stats
