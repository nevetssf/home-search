"""Named filter sets — persisted, per-user filter criteria for List/Map views.

Each set's ``payload`` is opaque JSON owned by the frontend (value filters +
filter regions). Scoped to the current user; names are unique per user.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import FilterSet, User

router = APIRouter(prefix="/filter-sets", tags=["filter-sets"])


@router.get("", response_model=List[schemas.FilterSetOut])
def list_filter_sets(
    db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    return (
        db.query(FilterSet)
        .filter(FilterSet.user_id == current.id)
        .order_by(FilterSet.name)
        .all()
    )


@router.post("", response_model=schemas.FilterSetOut, status_code=201)
def create_filter_set(
    payload: schemas.FilterSetCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if (
        db.query(FilterSet)
        .filter(FilterSet.user_id == current.id, FilterSet.name == payload.name)
        .first()
    ):
        raise HTTPException(409, "A filter set with that name already exists")
    fs = FilterSet(user_id=current.id, name=payload.name, payload=payload.payload or {})
    db.add(fs)
    db.commit()
    db.refresh(fs)
    return fs


def _owned(db: Session, set_id: int, current: User) -> FilterSet:
    fs = db.get(FilterSet, set_id)
    if not fs or fs.user_id != current.id:
        raise HTTPException(404, "Filter set not found")
    return fs


@router.patch("/{set_id}", response_model=schemas.FilterSetOut)
def update_filter_set(
    set_id: int,
    payload: schemas.FilterSetUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    fs = _owned(db, set_id, current)
    if payload.name is not None and payload.name != fs.name:
        clash = (
            db.query(FilterSet)
            .filter(
                FilterSet.user_id == current.id,
                FilterSet.name == payload.name,
                FilterSet.id != fs.id,
            )
            .first()
        )
        if clash:
            raise HTTPException(409, "A filter set with that name already exists")
        fs.name = payload.name
    if payload.payload is not None:
        fs.payload = payload.payload
    db.commit()
    db.refresh(fs)
    return fs


@router.delete("/{set_id}", status_code=204)
def delete_filter_set(
    set_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    fs = _owned(db, set_id, current)
    db.delete(fs)
    db.commit()
