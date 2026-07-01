"""Redfin "Download All" CSV import for bulk area seeding (PLAN.md §6).

Redfin's export has stable, human-readable headers; we map the columns we care
about and stash the whole row under ``raw`` for anything bespoke. Free and
offline — no API involved.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedRow:
    source_id: Optional[str]
    source_url: Optional[str]
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price: Optional[float] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lot_size: Optional[float] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = None
    days_on_market: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def _f(row: Dict[str, str], *keys: str) -> Optional[float]:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", ""))
            except ValueError:
                continue
    return None


def _i(row: Dict[str, str], *keys: str) -> Optional[int]:
    f = _f(row, *keys)
    return int(f) if f is not None else None


def _s(row: Dict[str, str], *keys: str) -> Optional[str]:
    for k in keys:
        v = row.get(k)
        if v:
            return v
    return None


def parse_csv(content: bytes) -> List[NormalizedRow]:
    """Parse a Redfin export into normalized rows. Tolerates header variation."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: List[NormalizedRow] = []
    for row in reader:
        # Redfin's "LOT SIZE" is in square feet; convert to our acres unit.
        lot_sqft = _f(row, "LOT SIZE")
        lot_acres = round(lot_sqft / 43560.0, 3) if lot_sqft is not None else None
        rows.append(
            NormalizedRow(
                source_id=_s(row, "MLS#", "LISTING ID"),
                source_url=_s(row, "URL", "URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)"),
                address=_s(row, "ADDRESS"),
                city=_s(row, "CITY"),
                state=_s(row, "STATE OR PROVINCE", "STATE"),
                zip=_s(row, "ZIP OR POSTAL CODE", "ZIP"),
                latitude=_f(row, "LATITUDE"),
                longitude=_f(row, "LONGITUDE"),
                price=_f(row, "PRICE"),
                beds=_f(row, "BEDS"),
                baths=_f(row, "BATHS"),
                sqft=_f(row, "SQUARE FEET"),
                lot_size=lot_acres,
                year_built=_i(row, "YEAR BUILT"),
                property_type=_s(row, "PROPERTY TYPE"),
                days_on_market=_i(row, "DAYS ON MARKET"),
                raw=dict(row),
            )
        )
    return rows
