from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Write content atomically via a temp-file rename (crash-safe)."""
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_,
        suffix=".tmp", delete=False
    ) as f:
        f.write(content)
        tmp_path = f.name
    os.replace(tmp_path, path)  # atomic on POSIX; near-atomic on Windows
