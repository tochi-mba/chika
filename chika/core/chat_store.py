from __future__ import annotations
import json
import time
from pathlib import Path


class ChatStore:
    """Persists chat sessions as JSON under profiles/<name>/chats/<session_id>.json"""

    def __init__(self, profiles_dir: Path) -> None:
        self._profiles_dir = profiles_dir

    def _chat_dir(self, profile: str) -> Path:
        d = self._profiles_dir / profile / "chats"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, profile: str, session_id: str, messages: list[dict], title: str = "") -> None:
        path = self._chat_dir(profile) / f"{session_id}.json"
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        data = {
            "id": session_id,
            "profile": profile,
            "title": title or existing.get("title", ""),
            "created_at": existing.get("created_at", time.time()),
            "updated_at": time.time(),
            "messages": messages,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, profile: str, session_id: str) -> dict | None:
        path = self._chat_dir(profile) / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def update_title(self, profile: str, session_id: str, title: str) -> None:
        path = self._chat_dir(profile) / f"{session_id}.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["title"] = title
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def list_chats(self, profile: str) -> list[dict]:
        chat_dir = self._profiles_dir / profile / "chats"
        if not chat_dir.exists():
            return []
        chats = []
        for f in chat_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                msgs = data.get("messages", [])
                preview = ""
                for m in reversed(msgs):
                    if m.get("role") in ("user", "assistant"):
                        content = m.get("content")
                        if isinstance(content, str) and content.strip():
                            preview = content.strip()[:80]
                            break
                chats.append({
                    "id": data["id"],
                    "title": data.get("title") or "New chat",
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": sum(1 for m in msgs if m.get("role") in ("user", "assistant")),
                    "preview": preview,
                })
            except Exception:
                pass
        return sorted(chats, key=lambda c: c["updated_at"], reverse=True)

    def delete(self, profile: str, session_id: str) -> bool:
        path = self._profiles_dir / profile / "chats" / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def find_session_profile(self, session_id: str) -> str | None:
        """Scan all profile directories to find which one owns this session."""
        if not self._profiles_dir.exists():
            return None
        for profile_dir in self._profiles_dir.iterdir():
            if not profile_dir.is_dir():
                continue
            if (profile_dir / "chats" / f"{session_id}.json").exists():
                return profile_dir.name
        return None
