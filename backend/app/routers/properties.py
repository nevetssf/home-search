"""Properties: CRUD, status history, tags, notes, and the shared list/map query.

The list view and the map view hit the same ``GET /properties`` endpoint; the
map passes ``bbox`` and the list passes sort/filter params, including
criterion-based filters of the form ``criterion[<id>]=<op>:<val>`` (parsed from
raw query params since FastAPI can't model that key shape directly).
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_
from sqlalchemy.orm import Session, selectinload

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import (
    OBJECTIVE_USER_ID,
    Criterion,
    CriterionValue,
    Note,
    Property,
    PropertyTag,
    StatusHistory,
    Tag,
    User,
)

router = APIRouter(prefix="/properties", tags=["properties"])

# ── Criterion filter operators → SQLAlchemy column predicates ────────────────
_NUM_OPS = {
    "eq": lambda col, v: col == v,
    "ne": lambda col, v: col != v,
    "gt": lambda col, v: col > v,
    "gte": lambda col, v: col >= v,
    "lt": lambda col, v: col < v,
    "lte": lambda col, v: col <= v,
}


def _record_status(db: Session, prop: Property, new_status: str, source: str):
    """Append a StatusHistory row only when status actually changes."""
    if prop.status != new_status:
        db.add(
            StatusHistory(
                property_id=prop.id, status=new_status, source=source
            )
        )
        prop.status = new_status


def _parse_criterion_filters(request: Request) -> List[tuple[int, str, str]]:
    """Extract criterion[<id>]=<op>:<val> params → [(criterion_id, op, val)]."""
    out: List[tuple[int, str, str]] = []
    for key, raw in request.query_params.multi_items():
        if not (key.startswith("criterion[") and key.endswith("]")):
            continue
        try:
            cid = int(key[len("criterion[") : -1])
        except ValueError:
            continue
        # Form is "<op>:<val>"; a bare value (no colon) means equality.
        if ":" in raw:
            op, _, val = raw.partition(":")
        else:
            op, val = "eq", raw
        out.append((cid, op or "eq", val))
    return out


@router.get("", response_model=List[schemas.PropertyOut])
def list_properties(
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    status: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    beds: Optional[float] = None,
    baths: Optional[float] = None,
    property_type: Optional[str] = None,
    tags: Optional[str] = Query(None, description="comma-separated tag names"),
    bbox: Optional[str] = Query(
        None, description="map bounds: minLng,minLat,maxLng,maxLat"
    ),
    archived: bool = False,
    sort: str = Query("created_at", description="field, prefix '-' for desc"),
    limit: int = 500,
):
    q = db.query(Property).options(selectinload(Property.tags))
    q = q.filter(Property.archived == archived)

    if status:
        q = q.filter(Property.status == status)
    if min_price is not None:
        q = q.filter(Property.price >= min_price)
    if max_price is not None:
        q = q.filter(Property.price <= max_price)
    if beds is not None:
        q = q.filter(Property.beds >= beds)
    if baths is not None:
        q = q.filter(Property.baths >= baths)
    if property_type:
        q = q.filter(Property.property_type == property_type)

    if tags:
        names = [t.strip() for t in tags.split(",") if t.strip()]
        for name in names:  # AND across tags
            q = q.filter(Property.tags.any(Tag.name == name))

    if bbox:
        try:
            min_lng, min_lat, max_lng, max_lat = (float(x) for x in bbox.split(","))
        except ValueError:
            raise HTTPException(400, "bbox must be minLng,minLat,maxLng,maxLat")
        q = q.filter(
            and_(
                Property.longitude >= min_lng,
                Property.longitude <= max_lng,
                Property.latitude >= min_lat,
                Property.latitude <= max_lat,
            )
        )

    # criterion[<id>]=<op>:<val> filters → typed JOIN per criterion (PLAN.md §4)
    for cid, op, val in _parse_criterion_filters(request):
        crit = db.get(Criterion, cid)
        if not crit:
            continue
        sub = db.query(CriterionValue.property_id).filter(
            CriterionValue.criterion_id == cid,
            CriterionValue.user_id == OBJECTIVE_USER_ID,
        )
        if crit.value_type == "boolean":
            sub = sub.filter(CriterionValue.value_bool == (val.lower() in ("1", "true", "yes")))
        elif crit.value_type in ("number", "rating"):
            try:
                num = float(val)
            except ValueError:
                continue
            pred = _NUM_OPS.get(op, _NUM_OPS["eq"])
            sub = sub.filter(pred(CriterionValue.value_number, num))
        else:  # enum / text
            sub = sub.filter(CriterionValue.value_text == val)
        q = q.filter(Property.id.in_(sub))

    # Sorting
    desc = sort.startswith("-")
    field = sort.lstrip("-")
    col = getattr(Property, field, Property.created_at)
    q = q.order_by(col.desc() if desc else col.asc())

    return q.limit(limit).all()


@router.get("/{property_id}", response_model=schemas.PropertyDetailOut)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    prop = db.query(Property).options(
        selectinload(Property.tags),
        selectinload(Property.notes),
        selectinload(Property.media),
        selectinload(Property.status_history),
    ).get(property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    return prop


@router.post("", response_model=schemas.PropertyOut, status_code=201)
def create_property(
    payload: schemas.PropertyCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    if data.get("source") and data["source"] not in schemas.VALID_SOURCES:
        raise HTTPException(400, f"source must be one of {schemas.VALID_SOURCES}")
    status_val = data.pop("status", None) or "for_sale"
    if status_val not in schemas.VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {schemas.VALID_STATUSES}")
    prop = Property(**data, status=status_val)
    db.add(prop)
    db.flush()
    db.add(StatusHistory(property_id=prop.id, status=status_val, source="manual"))
    db.commit()
    db.refresh(prop)
    return prop


@router.patch("/{property_id}", response_model=schemas.PropertyOut)
def update_property(
    property_id: int,
    payload: schemas.PropertyUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    data = payload.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if new_status is not None:
        if new_status not in schemas.VALID_STATUSES:
            raise HTTPException(400, f"status must be one of {schemas.VALID_STATUSES}")
        _record_status(db, prop, new_status, source="manual")
    for k, v in data.items():
        setattr(prop, k, v)
    db.commit()
    db.refresh(prop)
    return prop


@router.delete("/{property_id}", status_code=204)
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    db.delete(prop)
    db.commit()


@router.get(
    "/{property_id}/status-history", response_model=List[schemas.StatusHistoryOut]
)
def status_history(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")
    return (
        db.query(StatusHistory)
        .filter(StatusHistory.property_id == property_id)
        .order_by(StatusHistory.observed_at)
        .all()
    )


# ── Tags on a property ───────────────────────────────────────────────────────
@router.put("/{property_id}/tags", response_model=schemas.PropertyOut)
def set_property_tags(
    property_id: int,
    tag_ids: List[int],
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    prop = db.query(Property).options(selectinload(Property.tags)).get(property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    prop.tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    db.commit()
    db.refresh(prop)
    return prop


# ── Notes on a property ──────────────────────────────────────────────────────
@router.get("/{property_id}/notes", response_model=List[schemas.NoteOut])
def list_notes(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(Note)
        .filter(Note.property_id == property_id)
        .order_by(Note.created_at.desc())
        .all()
    )


@router.post("/{property_id}/notes", response_model=schemas.NoteOut, status_code=201)
def add_note(
    property_id: int,
    payload: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")
    note = Note(property_id=property_id, user_id=current.id, body=payload.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{property_id}/notes/{note_id}", status_code=204)
def delete_note(
    property_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    note = db.get(Note, note_id)
    if not note or note.property_id != property_id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
