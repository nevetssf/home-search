"""Freeform property labels (PLAN.md §4)."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Tag, User

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=List[schemas.TagOut])
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Tag).order_by(Tag.name).all()


@router.post("", response_model=schemas.TagOut, status_code=201)
def create_tag(
    payload: schemas.TagCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if db.query(Tag).filter(Tag.name == payload.name).first():
        raise HTTPException(409, "Tag already exists")
    tag = Tag(name=payload.name, color=payload.color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.put("/{tag_id}", response_model=schemas.TagOut)
def update_tag(
    tag_id: int,
    payload: schemas.TagUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(tag, k, v)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=204)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.delete(tag)
    db.commit()
