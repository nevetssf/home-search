"""SQLAlchemy ORM models. See PLAN.md §4 for the data-model rationale.

Common listing fields are first-class columns (fast to query/filter); bespoke
attributes live in the flexible typed-criteria system (Criterion / CriterionValue).
Designed to port cleanly to Postgres — no SQLite-only constructs.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from .database import Base

# ── Constants (kept as plain strings for portability; validated in schemas) ──
PROPERTY_STATUSES = ("for_sale", "pending", "sold", "off_market", "coming_soon")
PROPERTY_SOURCES = ("zillow", "redfin", "manual")
MEDIA_KINDS = ("photo", "video", "doc")
MEDIA_ORIGINS = ("promo", "upload")
CRITERION_VALUE_TYPES = ("boolean", "number", "rating", "enum", "text")
# Sentinel for the "objective / shared" value in CriterionValue.user_id — SQLite
# treats NULLs as distinct in unique indexes, so we coalesce to 0 instead.
OBJECTIVE_USER_ID = 0


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    pois = relationship(
        "PointOfInterest", back_populates="user", cascade="all, delete-orphan"
    )


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Source / cache
    source = Column(String, default="manual")  # zillow | redfin | realtor | manual
    source_url = Column(String, nullable=True)
    source_id = Column(String, index=True, nullable=True)  # e.g. zpid
    raw_payload = Column(JSON, nullable=True)  # full cached API response
    last_synced_at = Column(DateTime, nullable=True)

    # Location
    address = Column(String, nullable=True)
    city = Column(String, index=True, nullable=True)
    state = Column(String, index=True, nullable=True)
    zip = Column(String, index=True, nullable=True)
    county = Column(String, nullable=True)
    latitude = Column(Float, index=True, nullable=True)
    longitude = Column(Float, index=True, nullable=True)

    # Listing facts
    price = Column(Float, index=True, nullable=True)
    beds = Column(Float, index=True, nullable=True)
    baths = Column(Float, index=True, nullable=True)
    sqft = Column(Float, nullable=True)
    lot_size = Column(Float, nullable=True)  # acres
    year_built = Column(Integer, nullable=True)
    property_type = Column(String, index=True, nullable=True)

    status = Column(String, default="for_sale", index=True)
    days_on_market = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    archived = Column(Boolean, default=False, index=True)

    # Relationships
    status_history = relationship(
        "StatusHistory",
        back_populates="property",
        cascade="all, delete-orphan",
        order_by="StatusHistory.observed_at",
    )
    media = relationship(
        "Media", back_populates="property", cascade="all, delete-orphan"
    )
    notes = relationship(
        "Note", back_populates="property", cascade="all, delete-orphan"
    )
    tags = relationship(
        "Tag", secondary="property_tags", back_populates="properties"
    )
    criterion_values = relationship(
        "CriterionValue", back_populates="property", cascade="all, delete-orphan"
    )
    distances = relationship(
        "PlaceDistance", back_populates="property", cascade="all, delete-orphan"
    )


class StatusHistory(Base):
    """Append-only. The scheduler writes a row only when status changes."""

    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    status = Column(String, nullable=False)
    observed_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String, nullable=True)

    property = relationship("Property", back_populates="status_history")


class Media(Base):
    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    kind = Column(String, default="photo")  # photo | video | doc
    origin = Column(String, default="upload")  # promo | upload
    storage_key = Column(String, nullable=False)  # resolved via storage abstraction
    content_type = Column(String, nullable=True)
    caption = Column(String, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    property = relationship("Property", back_populates="media")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    color = Column(String, nullable=True)

    properties = relationship(
        "Property", secondary="property_tags", back_populates="tags"
    )


class PropertyTag(Base):
    __tablename__ = "property_tags"

    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id = Column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    property = relationship("Property", back_populates="notes")
    user = relationship("User", back_populates="notes")


class PointOfInterest(Base):
    """Fixed places the household cares about (primary home, an office)."""

    __tablename__ = "points_of_interest"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="pois")


class PlaceDistance(Base):
    """Cached amenity result. category: grocery|cafe|restaurant|downtown|poi:<id>."""

    __tablename__ = "place_distances"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    category = Column(String, index=True, nullable=False)
    place_name = Column(String, nullable=True)
    place_address = Column(String, nullable=True)
    distance_meters = Column(Float, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    mode = Column(String, default="driving")  # driving | walking
    computed_at = Column(DateTime, default=datetime.utcnow)
    raw = Column(JSON, nullable=True)

    property = relationship("Property", back_populates="distances")


# ── Flexible typed criteria (PLAN.md §4) ─────────────────────────────────────


class Criterion(Base):
    """A criterion definition — add/edit anytime, no code change.

    is_subjective=False => one shared objective value per property.
    is_subjective=True  => a value recorded per user.
    """

    __tablename__ = "criteria"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    value_type = Column(String, nullable=False)  # boolean|number|rating|enum|text
    unit = Column(String, nullable=True)  # acres, trees, min, ...
    scale_min = Column(Integer, nullable=True)  # rating
    scale_max = Column(Integer, nullable=True)  # rating
    options = Column(JSON, nullable=True)  # enum choices
    is_subjective = Column(Boolean, default=False)
    weight = Column(Float, default=1.0)  # contribution to weighted score
    sort_order = Column(Integer, default=0)
    active = Column(Boolean, default=True)

    values = relationship(
        "CriterionValue", back_populates="criterion", cascade="all, delete-orphan"
    )


class CriterionValue(Base):
    """One unified table for every criterion value (objective and subjective).

    user_id = OBJECTIVE_USER_ID (0) => objective/shared value.
    user_id = <a real user id>      => that user's subjective rating.
    The typed column used is decided by the criterion's value_type
    (rating is stored in value_number).
    """

    __tablename__ = "criterion_values"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "criterion_id", "user_id", name="uq_criterion_value"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(
        Integer, ForeignKey("properties.id", ondelete="CASCADE"), index=True
    )
    criterion_id = Column(
        Integer, ForeignKey("criteria.id", ondelete="CASCADE"), index=True
    )
    # Coalesced to a non-null sentinel (0) so the unique index behaves under SQLite.
    user_id = Column(Integer, default=OBJECTIVE_USER_ID, nullable=False)

    value_number = Column(Float, nullable=True)
    value_bool = Column(Boolean, nullable=True)
    value_text = Column(Text, nullable=True)

    note = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    criterion = relationship("Criterion", back_populates="values")
    property = relationship("Property", back_populates="criterion_values")
