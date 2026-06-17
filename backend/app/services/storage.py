"""Media storage abstraction (PLAN.md §11).

A backend-agnostic key/value blob store. ``local`` writes under MEDIA_ROOT;
``s3`` targets any S3-compatible bucket. Media rows store only the opaque
``storage_key``; switching backends is a config change, not a code change.

Keys are namespaced ``properties/<id>/<uuid><ext>`` and are never user-supplied
paths, so traversal is not possible.
"""
from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, Tuple

from ..config import settings


def make_key(property_id: int, filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    return f"properties/{property_id}/{uuid.uuid4().hex}{ext}"


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        ...

    @abstractmethod
    def open(self, key: str) -> Tuple[BinaryIO, Optional[str]]:
        """Return (file-like, content_type). Caller closes the stream."""

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...


class LocalStorage(StorageBackend):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Resolve and confirm the key stays within root (defense in depth).
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("storage key escapes media root")
        return p

    def save(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def open(self, key: str) -> Tuple[BinaryIO, Optional[str]]:
        return open(self._path(key), "rb"), None

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage(StorageBackend):
    def __init__(self):
        import boto3  # imported lazily so local installs don't need it loaded

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
        )

    def save(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def open(self, key: str) -> Tuple[BinaryIO, Optional[str]]:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"], obj.get("ContentType")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


_backend: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """Singleton storage backend chosen by STORAGE_BACKEND."""
    global _backend
    if _backend is None:
        if settings.storage_backend == "s3":
            _backend = S3Storage()
        else:
            _backend = LocalStorage(settings.media_root)
    return _backend


def reset_storage() -> None:
    """Test hook — drop the cached backend so a new MEDIA_ROOT takes effect."""
    global _backend
    _backend = None
