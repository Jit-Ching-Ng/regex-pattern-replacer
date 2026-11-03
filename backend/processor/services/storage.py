"""
Snapshot storage.

Every dataset version (the parsed upload and the result of each operation) is
written once as a Parquet file and never modified. Because snapshots are
immutable they can be cached in memory safely, which makes paging through a
large table cheap: the file is parsed once, every page afterwards is a slice.

Parquet was chosen over re-reading CSV because it is columnar, compressed and
preserves column names/order exactly.
"""
from __future__ import annotations

import shutil
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import pandas as pd
from django.conf import settings


class SnapshotStore:
    def __init__(self, root: Path, cache_size: int = 6) -> None:
        self.root = Path(root)
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._cache_size = cache_size
        self._lock = Lock()

    def dataset_dir(self, dataset_id: uuid.UUID | str) -> Path:
        return self.root / "datasets" / str(dataset_id)

    def write(self, dataset_id: uuid.UUID | str, frame: pd.DataFrame, label: str) -> str:
        """Persist ``frame`` and return its path relative to the storage root."""
        directory = self.dataset_dir(dataset_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{label}-{uuid.uuid4().hex[:8]}.parquet"
        frame.to_parquet(path, index=False)
        relative = str(path.relative_to(self.root))
        self._remember(relative, frame)
        return relative

    def read(self, relative_path: str) -> pd.DataFrame:
        """Return a snapshot. The returned frame is shared: treat it as read-only."""
        with self._lock:
            frame = self._cache.get(relative_path)
            if frame is not None:
                self._cache.move_to_end(relative_path)
                return frame
        frame = pd.read_parquet(self.root / relative_path)
        self._remember(relative_path, frame)
        return frame

    def delete(self, relative_path: str) -> None:
        with self._lock:
            self._cache.pop(relative_path, None)
        (self.root / relative_path).unlink(missing_ok=True)

    def delete_dataset(self, dataset_id: uuid.UUID | str) -> None:
        prefix = str(Path("datasets") / str(dataset_id))
        with self._lock:
            for key in [key for key in self._cache if key.startswith(prefix)]:
                del self._cache[key]
        shutil.rmtree(self.dataset_dir(dataset_id), ignore_errors=True)

    def _remember(self, relative_path: str, frame: pd.DataFrame) -> None:
        with self._lock:
            self._cache[relative_path] = frame
            self._cache.move_to_end(relative_path)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


_store: SnapshotStore | None = None


def get_store() -> SnapshotStore:
    global _store
    if _store is None or _store.root != Path(settings.MEDIA_ROOT):
        _store = SnapshotStore(Path(settings.MEDIA_ROOT))
    return _store
