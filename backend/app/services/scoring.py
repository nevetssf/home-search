"""Weighted scoring for the flexible-criteria system (PLAN.md §4).

Only *subjective* ``rating`` criteria contribute to a score. Each rating is
normalized to 0..1 against its criterion's scale, averaged across users
(household view), then combined as a weight-weighted mean. Objective
booleans/numbers don't score — they drive filters instead.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from ..models import OBJECTIVE_USER_ID, Criterion, CriterionValue


def _scale_bounds(criterion: Criterion) -> tuple[float, float]:
    lo = criterion.scale_min if criterion.scale_min is not None else 1
    hi = criterion.scale_max if criterion.scale_max is not None else 5
    if hi == lo:
        hi = lo + 1
    return float(lo), float(hi)


def normalize_rating(criterion: Criterion, raw: float) -> float:
    """Map a raw rating onto 0..1, clamped."""
    lo, hi = _scale_bounds(criterion)
    return max(0.0, min(1.0, (raw - lo) / (hi - lo)))


def aggregate_subjective(
    criteria_by_id: Dict[int, Criterion], values: Iterable[CriterionValue]
) -> Dict[int, float]:
    """criterion_id -> mean normalized (0..1) subjective rating across all users."""
    sums: Dict[int, List[float]] = {}
    for v in values:
        if v.user_id == OBJECTIVE_USER_ID or v.value_number is None:
            continue
        crit = criteria_by_id.get(v.criterion_id)
        if not crit or crit.value_type != "rating" or not crit.is_subjective:
            continue
        sums.setdefault(v.criterion_id, []).append(normalize_rating(crit, v.value_number))
    return {cid: sum(xs) / len(xs) for cid, xs in sums.items() if xs}


def overall_score(
    criteria_by_id: Dict[int, Criterion], values: Iterable[CriterionValue]
) -> Optional[float]:
    """Household weighted score in 0..1, or None if no subjective ratings exist.

    Weight per criterion is its ``weight``; the per-criterion input is the mean
    normalized rating across users.
    """
    means = aggregate_subjective(criteria_by_id, list(values))
    if not means:
        return None
    weighted = 0.0
    total_w = 0.0
    for cid, mean in means.items():
        w = criteria_by_id[cid].weight or 1.0
        weighted += w * mean
        total_w += w
    return weighted / total_w if total_w else None
