"""FastAPI application entrypoint — router includes + lifespan (PLAN.md §2).

All third-party API calls happen server-side; the browser only talks to this
app. The scheduler starts/stops with the app lifecycle.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import (
    auth, criteria, filter_sets, ingest, media, places, properties, tags,
)
from .services.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="home-search", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(properties.router)
app.include_router(tags.router)
app.include_router(criteria.router)
app.include_router(media.router)
app.include_router(places.router)
app.include_router(ingest.router)
app.include_router(filter_sets.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
