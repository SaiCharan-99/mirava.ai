"""Blob storage: Cloud Storage in the cloud, a local directory in dev — same API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from shared.settings import Settings, get_settings

IO_TIMEOUT_S = float(os.environ.get("FILES_TIMEOUT_S", "60"))   # per GCS request (fix-E: no hung ticks)


class Files(Protocol):
    """Read/write bytes by (bucket, key)."""

    def write(self, bucket: str, key: str, data: bytes) -> str: ...
    def read(self, bucket: str, key: str) -> bytes: ...
    def exists(self, bucket: str, key: str) -> bool: ...


class LocalFiles:
    """Files under LOCAL_FILES_DIR/<bucket>/<key>."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _p(self, bucket: str, key: str) -> Path:
        p = (self.root / (bucket or "default") / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("key escapes the storage root")
        return p

    def write(self, bucket: str, key: str, data: bytes) -> str:
        """Write bytes; returns a file URI."""
        p = self._p(bucket, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p.as_uri()

    def read(self, bucket: str, key: str) -> bytes:
        """Read bytes."""
        return self._p(bucket, key).read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        """True if the object exists."""
        return self._p(bucket, key).exists()


class GCSFiles:
    """google-cloud-storage."""

    def __init__(self, settings: Settings) -> None:
        from google.cloud import storage  # type: ignore[attr-defined]

        self.client: Any = storage.Client(project=settings.gcp_project_id)

    def write(self, bucket: str, key: str, data: bytes) -> str:
        """Upload bytes; returns a gs:// URI."""
        self.client.bucket(bucket).blob(key).upload_from_string(data, timeout=IO_TIMEOUT_S)
        return f"gs://{bucket}/{key}"

    def read(self, bucket: str, key: str) -> bytes:
        """Download bytes."""
        return self.client.bucket(bucket).blob(key).download_as_bytes(timeout=IO_TIMEOUT_S)

    def exists(self, bucket: str, key: str) -> bool:
        """True if the object exists."""
        return self.client.bucket(bucket).blob(key).exists(timeout=IO_TIMEOUT_S)


def get_files(settings: Settings | None = None) -> Files:
    """Local disk when ENV=local, else GCS."""
    s = settings or get_settings()
    return LocalFiles(s.local_files_dir) if s.env == "local" else GCSFiles(s)
