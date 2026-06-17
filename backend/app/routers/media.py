"""Media upload/serve via the storage abstraction (PLAN.md §4, §11).

Files are streamed back through the backend (never hotlinked) so the app stays
private and promo photos survive a delisting. The browser never sees a storage
path — only ``/media/{id}/file``.
"""
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Media, Property, User
from ..services.storage import get_storage, make_key

router = APIRouter(prefix="/media", tags=["media"])


def _with_url(m: Media) -> schemas.MediaOut:
    out = schemas.MediaOut.model_validate(m)
    out.url = f"/media/{m.id}/file"
    return out


@router.get("", response_model=List[schemas.MediaOut])
def list_media(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items = (
        db.query(Media)
        .filter(Media.property_id == property_id)
        .order_by(Media.sort_order, Media.id)
        .all()
    )
    return [_with_url(m) for m in items]


@router.post("", response_model=schemas.MediaOut, status_code=201)
def upload_media(
    property_id: int = Form(...),
    kind: str = Form("photo"),
    caption: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not db.get(Property, property_id):
        raise HTTPException(404, "Property not found")
    if kind not in schemas.VALID_MEDIA_KINDS:
        raise HTTPException(400, f"kind must be one of {schemas.VALID_MEDIA_KINDS}")

    data = file.file.read()
    key = make_key(property_id, file.filename or "upload.bin")
    get_storage().save(key, data, content_type=file.content_type)

    m = Media(
        property_id=property_id,
        kind=kind,
        origin="upload",
        storage_key=key,
        content_type=file.content_type,
        caption=caption,
        uploaded_by=current.id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _with_url(m)


@router.get("/{media_id}/file")
def get_media_file(
    media_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    m = db.get(Media, media_id)
    if not m:
        raise HTTPException(404, "Media not found")
    stream, content_type = get_storage().open(m.storage_key)
    return StreamingResponse(
        stream, media_type=content_type or m.content_type or "application/octet-stream"
    )


@router.patch("/{media_id}", response_model=schemas.MediaOut)
def update_media(
    media_id: int,
    payload: schemas.MediaUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    m = db.get(Media, media_id)
    if not m:
        raise HTTPException(404, "Media not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return _with_url(m)


@router.delete("/{media_id}", status_code=204)
def delete_media(
    media_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    m = db.get(Media, media_id)
    if not m:
        raise HTTPException(404, "Media not found")
    try:
        get_storage().delete(m.storage_key)
    except Exception:
        pass  # orphaned blob is harmless; don't block the row delete
    db.delete(m)
    db.commit()
