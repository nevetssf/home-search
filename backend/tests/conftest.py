"""Pytest fixtures: a fresh temp SQLite DB + media dir per test, an auth'd client.

Each test gets an isolated database and a TestClient whose ``get_db`` and
storage backend point at that scratch space, so tests never touch real data.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure env before importing the app so settings pick it up.
_tmpdir = tempfile.mkdtemp(prefix="home-search-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["MEDIA_ROOT"] = f"{_tmpdir}/media"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STATUS_REFRESH_ENABLED"] = "false"
os.environ["GOOGLE_MAPS_API_KEY"] = ""
os.environ["RAPIDAPI_KEY"] = ""

from app.auth import get_password_hash  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.services import storage  # noqa: E402


@pytest.fixture
def db_session():
    """A brand-new database engine/schema per test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    media_dir = tempfile.mkdtemp(prefix="media-")
    storage._backend = storage.LocalStorage(media_dir)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        os.unlink(path)
        storage.reset_storage()


@pytest.fixture
def client(db_session):
    """TestClient wired to the per-test session, with one seeded user logged in."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    user = User(
        email="steve@example.com",
        name="Steve",
        hashed_password=get_password_hash("password123"),
    )
    db_session.add(user)
    db_session.commit()

    c = TestClient(app)
    resp = c.post(
        "/auth/login",
        json={"email": "steve@example.com", "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_property(client):
    """Factory: create a property and return its JSON."""
    def _make(**overrides):
        payload = {
            "address": "123 Vine St",
            "city": "Sebastopol",
            "state": "CA",
            "price": 1200000,
            "beds": 3,
            "baths": 2,
            "latitude": 38.4,
            "longitude": -122.8,
        }
        payload.update(overrides)
        r = client.post("/properties", json=payload)
        assert r.status_code == 201, r.text
        return r.json()

    return _make
