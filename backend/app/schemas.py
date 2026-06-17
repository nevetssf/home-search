"""Pydantic request/response models.

Naming convention: ``XCreate`` / ``XUpdate`` for input, ``XOut`` for output.
``from_attributes`` lets these read straight off SQLAlchemy ORM objects.
"""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import (
    CRITERION_VALUE_TYPES,
    MEDIA_KINDS,
    MEDIA_ORIGINS,
    PROPERTY_SOURCES,
    PROPERTY_STATUSES,
)


# ── Auth ─────────────────────────────────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    name: str
    created_at: datetime


# ── Tags ─────────────────────────────────────────────────────────────────────
class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    color: Optional[str] = None


# ── Notes ────────────────────────────────────────────────────────────────────
class NoteCreate(BaseModel):
    body: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    property_id: int
    user_id: Optional[int] = None
    body: str
    created_at: datetime


# ── Status history ────────────────────────────────────────────────────────────
class StatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    observed_at: datetime
    source: Optional[str] = None


# ── Media ────────────────────────────────────────────────────────────────────
class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    property_id: int
    kind: str
    origin: str
    caption: Optional[str] = None
    content_type: Optional[str] = None
    sort_order: int = 0
    created_at: datetime
    url: Optional[str] = None  # populated by router: /media/{id}/file


class MediaUpdate(BaseModel):
    caption: Optional[str] = None
    sort_order: Optional[int] = None


# ── Properties ───────────────────────────────────────────────────────────────
class PropertyBase(BaseModel):
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    county: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price: Optional[float] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lot_size: Optional[float] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = None
    status: Optional[str] = None
    days_on_market: Optional[int] = None
    description: Optional[str] = None


class PropertyCreate(PropertyBase):
    source: str = "manual"
    source_url: Optional[str] = None
    source_id: Optional[str] = None


class PropertyUpdate(PropertyBase):
    archived: Optional[bool] = None


class PropertyOut(PropertyBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    source_url: Optional[str] = None
    source_id: Optional[str] = None
    archived: bool
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    tags: List[TagOut] = []


class PropertyDetailOut(PropertyOut):
    """Property plus its child collections, for the detail page."""

    raw_payload: Optional[Any] = None  # full cached source response
    notes: List[NoteOut] = []
    media: List[MediaOut] = []
    status_history: List[StatusHistoryOut] = []


# ── Flexible criteria ────────────────────────────────────────────────────────
class CriterionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    value_type: str
    unit: Optional[str] = None
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    options: Optional[List[str]] = None
    is_subjective: bool = False
    weight: float = 1.0
    sort_order: int = 0
    active: bool = True


class CriterionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    options: Optional[List[str]] = None
    weight: Optional[float] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    value_type: str
    unit: Optional[str] = None
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    options: Optional[List[str]] = None
    is_subjective: bool
    weight: float
    sort_order: int
    active: bool


class CriterionValueSet(BaseModel):
    """Set a value for a criterion. For subjective criteria, the value is the
    requesting user's rating; for objective ones it's the shared value."""

    value_number: Optional[float] = None
    value_bool: Optional[bool] = None
    value_text: Optional[str] = None
    note: Optional[str] = None


class CriterionValueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    criterion_id: int
    user_id: int
    value_number: Optional[float] = None
    value_bool: Optional[bool] = None
    value_text: Optional[str] = None
    note: Optional[str] = None
    updated_at: datetime


class PropertyCriteriaOut(BaseModel):
    """Everything the detail page needs to render the criteria panel."""

    objective: List[CriterionValueOut] = []
    my_ratings: List[CriterionValueOut] = []
    # criterion_id -> mean subjective rating across all users (normalized 0..1 * scale)
    aggregate_ratings: dict = {}
    overall_score: Optional[float] = None  # household weighted score, 0..1


# ── Points of interest & distances ─────────────────────────────────────────────
class POICreate(BaseModel):
    name: str
    latitude: float
    longitude: float


class POIOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    latitude: float
    longitude: float


class PlaceDistanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    place_name: Optional[str] = None
    place_address: Optional[str] = None
    distance_meters: Optional[float] = None
    duration_seconds: Optional[float] = None
    mode: str
    computed_at: datetime


# ── Ingestion ──────────────────────────────────────────────────────────────────
class ZillowURLIngest(BaseModel):
    url: str


class ZillowSearchIngest(BaseModel):
    location: str
    status_type: Optional[str] = "ForSale"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    beds_min: Optional[int] = None
    home_type: Optional[str] = None


class IngestResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    property_ids: List[int] = []
    errors: List[str] = []
    raw_available: bool = True


# Validation helpers reused by routers
VALID_STATUSES = set(PROPERTY_STATUSES)
VALID_SOURCES = set(PROPERTY_SOURCES)
VALID_VALUE_TYPES = set(CRITERION_VALUE_TYPES)
VALID_MEDIA_KINDS = set(MEDIA_KINDS)
VALID_MEDIA_ORIGINS = set(MEDIA_ORIGINS)
