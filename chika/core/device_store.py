from __future__ import annotations

import json
import secrets
import time
from pathlib import Path


class DeviceStore:
    """
    Maps device_id → current_session_id. Persisted as individual JSON files
    under data/devices/<device_id>.json so server restarts don't lose mappings.
    """

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "devices"
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_device_id() -> str:
        return "dev_" + secrets.token_hex(8)

    def _path(self, device_id: str) -> Path:
        return self._dir / f"{device_id}.json"

    def get_session(self, device_id: str) -> str | None:
        p = self._path(device_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8")).get("current_session_id")
        except Exception:
            return None

    def set_session(self, device_id: str, session_id: str) -> None:
        p = self._path(device_id)
        existing: dict = {}
        if p.exists():
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update({
            "device_id": device_id,
            "current_session_id": session_id,
            "last_seen": time.time(),
        })
        if "created_at" not in existing:
            existing["created_at"] = time.time()
        p.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def exists(self, device_id: str) -> bool:
        return self._path(device_id).exists()
