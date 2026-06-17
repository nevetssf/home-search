"""Flexible typed criteria: definitions + values + per-property aggregates.

Definitions live in ``/criteria``; values are set/read under a property at
``/properties/{id}/criteria``. A criterion's ``is_subjective`` flag decides
whether a written value is shared (objective) or scoped to the current user.
See PLAN.md §4 and ``services/scoring.py``.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import (
    OBJECTIVE_USER_ID,
    Criterion,
    CriterionValue,
    Property,
    User,
)
from ..services import scoring

router = APIRouter(tags=["criteria"])


# ── Criterion definitions ────────────────────────────────────────────────────
@router.get("/criteria", response_model=List[schemas.CriterionOut])
def list_criteria(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Criterion)
    if not include_inactive:
        q = q.filter(Criterion.active.is_(True))
    return q.order_by(Criterion.sort_order, Criterion.id).all()


@router.post("/criteria", response_model=schemas.CriterionOut, status_code=201)
def create_criterion(
    payload: schemas.CriterionCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if payload.value_type not in schemas.VALID_VALUE_TYPES:
        raise HTTPException(400, f"value_type must be one of {schemas.VALID_VALUE_TYPES}")
    if payload.value_type == "rating":
        if payload.scale_min is None or payload.scale_max is None:
            raise HTTPException(400, "rating criteria require scale_min and scale_max")
        if payload.scale_max <= payload.scale_min:
            raise HTTPException(400, "scale_max must be greater than scale_min")
    if payload.value_type == "enum" and not payload.options:
        raise HTTPException(400, "enum criteria require options")
    crit = Criterion(**payload.model_dump())
    db.add(crit)
    db.commit()
    db.refresh(crit)
    return crit


@router.patch("/criteria/{criterion_id}", response_model=schemas.CriterionOut)
def update_criterion(
    criterion_id: int,
    payload: schemas.CriterionUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    crit = db.get(Criterion, criterion_id)
    if not crit:
        raise HTTPException(404, "Criterion not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(crit, k, v)
    db.commit()
    db.refresh(crit)
    return crit


@router.delete("/criteria/{criterion_id}", status_code=204)
def delete_criterion(
    criterion_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    crit = db.get(Criterion, criterion_id)
    if not crit:
        raise HTTPException(404, "Criterion not found")
    db.delete(crit)
    db.commit()


# ── Values on a property ─────────────────────────────────────────────────────
def _assign_typed_value(
    crit: Criterion, cv: CriterionValue, payload: schemas.CriterionValueSet
):
    """Write the payload into the column dictated by the criterion type."""
    cv.value_number = cv.value_bool = cv.value_text = None
    if crit.value_type == "boolean":
        cv.value_bool = bool(payload.value_bool)
    elif crit.value_type in ("number", "rating"):
        if payload.value_number is None:
            raise HTTPException(400, f"{crit.value_type} criterion needs value_number")
        if crit.value_type == "rating" and not (
            (crit.scale_min or 1) <= payload.value_number <= (crit.scale_max or 5)
        ):
            raise HTTPException(400, "rating out of scale range")
        cv.value_number = payload.value_number
    elif crit.value_type == "enum":
        if crit.options and payload.value_text not in crit.options:
            raise HTTPException(400, f"value must be one of {crit.options}")
        cv.value_text = payload.value_text
    else:  # text
        cv.value_text = payload.value_text
    cv.note = payload.note


@router.put(
    "/properties/{property_id}/criteria/{criterion_id}",
    response_model=schemas.CriterionValueOut,
)
def set_criterion_value(
    property_id: int,
    criterion_id: int,
    payload: schemas.CriterionValueSet,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")
    crit = db.get(Criterion, criterion_id)
    if not crit:
        raise HTTPException(404, "Criterion not found")

    # Subjective values are per-user; objective values are shared (sentinel id).
    uid = current.id if crit.is_subjective else OBJECTIVE_USER_ID
    cv = (
        db.query(CriterionValue)
        .filter_by(property_id=property_id, criterion_id=criterion_id, user_id=uid)
        .first()
    )
    if not cv:
        cv = CriterionValue(
            property_id=property_id, criterion_id=criterion_id, user_id=uid
        )
        db.add(cv)
    _assign_typed_value(crit, cv, payload)
    db.commit()
    db.refresh(cv)
    return cv


@router.get(
    "/properties/{property_id}/criteria", response_model=schemas.PropertyCriteriaOut
)
def get_property_criteria(
    property_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")

    values = (
        db.query(CriterionValue)
        .filter(CriterionValue.property_id == property_id)
        .all()
    )
    criteria_by_id: Dict[int, Criterion] = {
        c.id: c for c in db.query(Criterion).all()
    }

    objective = [v for v in values if v.user_id == OBJECTIVE_USER_ID]
    my_ratings = [v for v in values if v.user_id == current.id]
    aggregates = scoring.aggregate_subjective(criteria_by_id, values)
    overall = scoring.overall_score(criteria_by_id, values)

    return schemas.PropertyCriteriaOut(
        objective=objective,
        my_ratings=my_ratings,
        aggregate_ratings=aggregates,
        overall_score=overall,
    )
