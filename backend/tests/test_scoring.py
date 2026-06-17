"""Unit tests for the scoring service, incl. multi-user household combination."""
from app.models import Criterion, CriterionValue, OBJECTIVE_USER_ID
from app.services import scoring


def _rating(scale=(1, 5), weight=1.0, cid=1):
    return Criterion(
        id=cid, name="r", value_type="rating", is_subjective=True,
        scale_min=scale[0], scale_max=scale[1], weight=weight,
    )


def test_normalize_rating_bounds():
    c = _rating()
    assert scoring.normalize_rating(c, 1) == 0.0
    assert scoring.normalize_rating(c, 5) == 1.0
    assert scoring.normalize_rating(c, 3) == 0.5
    # clamps out-of-range
    assert scoring.normalize_rating(c, 99) == 1.0


def test_aggregate_is_mean_across_users():
    c = _rating(cid=1)
    by_id = {1: c}
    values = [
        CriterionValue(criterion_id=1, user_id=1, value_number=2),  # 0.25
        CriterionValue(criterion_id=1, user_id=2, value_number=4),  # 0.75
    ]
    agg = scoring.aggregate_subjective(by_id, values)
    assert abs(agg[1] - 0.5) < 1e-9


def test_overall_weighted_across_criteria():
    c1 = _rating(weight=1.0, cid=1)
    c2 = _rating(weight=3.0, cid=2)
    by_id = {1: c1, 2: c2}
    values = [
        CriterionValue(criterion_id=1, user_id=1, value_number=5),  # 1.0
        CriterionValue(criterion_id=2, user_id=1, value_number=1),  # 0.0
    ]
    # weighted: (1*1.0 + 3*0.0)/(1+3) = 0.25
    assert abs(scoring.overall_score(by_id, values) - 0.25) < 1e-9


def test_objective_values_excluded_from_score():
    c = _rating(cid=1)
    by_id = {1: c}
    values = [CriterionValue(criterion_id=1, user_id=OBJECTIVE_USER_ID, value_number=5)]
    assert scoring.overall_score(by_id, values) is None
