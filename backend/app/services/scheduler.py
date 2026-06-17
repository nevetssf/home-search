"""APScheduler status-refresh job (PLAN.md §6).

A bounded, scheduled job re-checks only ``for_sale``/``pending`` properties and
writes a ``StatusHistory`` row only on change — keeping API usage inside the
free/cheap tier. No-ops cleanly when no RapidAPI key is set.
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from ..database import SessionLocal
from ..models import Property, StatusHistory
from .zillow import ZillowClient, ZillowUnavailable, normalize

logger = logging.getLogger("home_search.scheduler")

_scheduler: AsyncIOScheduler | None = None

# Only these statuses are worth re-polling.
_REFRESHABLE = ("for_sale", "pending", "coming_soon")


def refresh_statuses() -> dict:
    """Re-poll active Zillow listings; record status changes. Returns a summary."""
    db = SessionLocal()
    summary = {"checked": 0, "changed": 0, "errors": 0}
    try:
        client = ZillowClient()
        props = (
            db.query(Property)
            .filter(
                Property.source == "zillow",
                Property.status.in_(_REFRESHABLE),
                Property.archived.is_(False),
                Property.source_id.isnot(None),
            )
            .all()
        )
        for prop in props:
            summary["checked"] += 1
            try:
                raw = client.fetch_by_url(prop.source_url or "")
                listing = normalize(raw)
                prop.last_synced_at = datetime.utcnow()
                if listing.status and listing.status != prop.status:
                    db.add(
                        StatusHistory(
                            property_id=prop.id,
                            status=listing.status,
                            source="scheduler",
                        )
                    )
                    prop.status = listing.status
                    summary["changed"] += 1
            except ZillowUnavailable:
                raise  # no key / wrapper down — abort the whole run
            except Exception as e:
                summary["errors"] += 1
                logger.warning("status refresh failed for %s: %s", prop.id, e)
        db.commit()
    except ZillowUnavailable as e:
        logger.info("status refresh skipped: %s", e)
    finally:
        db.close()
    logger.info("status refresh: %s", summary)
    return summary


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.status_refresh_enabled:
        logger.info("status refresh disabled")
        return None
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        refresh_statuses,
        CronTrigger(
            day_of_week=settings.status_refresh_day_of_week,
            hour=settings.status_refresh_hour,
            minute=0,
        ),
        id="status_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "scheduler started: %s @ %02d:00",
        settings.status_refresh_day_of_week,
        settings.status_refresh_hour,
    )
    return _scheduler


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
