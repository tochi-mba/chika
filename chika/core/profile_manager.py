from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Profile:
    name: str
    workspace: str    # absolute path to the profile's working directory
    memory_path: str  # absolute path to the profile's memory.md
    password_hash: str | None = field(default=None, repr=False)
    # Pet companion — id of an entry in chika._cli.pets.PETS. ``None`` means
    # the profile inherits the default pet. Each profile picks its own.
    pet_id: str | None = None


class ProfileManager:
    """
    Manages per-user profiles on disk.

    Structure:
        data/profiles/
            default/
                memory.md
                workspace/
                profile.json          ← metadata (password_hash, etc.)
            tochi/
                memory.md
                workspace/
                profile.json
    """

    def __init__(self, profiles_dir: str | Path) -> None:
        self._dir = Path(profiles_dir).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Disk helpers ──────────────────────────────────────────────────────────

    def _profile_json_path(self, name: str) -> Path:
        return self._dir / name / "profile.json"

    def _load_meta(self, name: str) -> dict:
        path = self._profile_json_path(name)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_meta(self, name: str, data: dict) -> None:
        path = self._profile_json_path(name)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── Profile CRUD ──────────────────────────────────────────────────────────

    def exists(self, name: str) -> bool:
        return (self._dir / name).is_dir()

    @staticmethod
    def _sanitize_name(name: str) -> str:
        name = name.strip().lower().replace(" ", "_")
        # Reject traversal and path separators before any stripping
        if ".." in name or "/" in name or "\\" in name:
            raise ValueError(f"Invalid profile name: {name!r}")
        name = name.lstrip(".")
        if not name:
            raise ValueError(f"Invalid profile name (empty after sanitization): {name!r}")
        return name

    def get_or_create(self, name: str) -> Profile:
        name = self._sanitize_name(name)
        profile_dir = self._dir / name
        profile_dir.mkdir(parents=True, exist_ok=True)
        workspace = profile_dir / "workspace"
        workspace.mkdir(exist_ok=True)
        meta = self._load_meta(name)
        return Profile(
            name=name,
            workspace=str(workspace),
            memory_path=str(profile_dir / "memory.md"),
            password_hash=meta.get("password_hash"),
            pet_id=meta.get("pet_id"),
        )

    def get(self, name: str) -> Profile | None:
        if not self.exists(name):
            return None
        return self.get_or_create(name)

    def list_profiles(self) -> list[str]:
        return sorted(d.name for d in self._dir.iterdir() if d.is_dir())

    # ── Password helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        """PBKDF2-HMAC-SHA256 with a random 16-byte salt. No extra dependencies."""
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()
        return f"{salt}:{h}"

    @staticmethod
    def _check_password(password: str, stored_hash: str) -> bool:
        """Constant-time comparison to prevent timing attacks."""
        if not stored_hash or ":" not in stored_hash:
            return False
        try:
            salt, h = stored_hash.split(":", 1)
            check = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                100_000,
            ).hex()
            return secrets.compare_digest(check, h)
        except Exception:
            return False

    # ── Password API ──────────────────────────────────────────────────────────

    def has_password(self, name: str) -> bool:
        """Return True if this profile has a password set."""
        meta = self._load_meta(name)
        return bool(meta.get("password_hash"))

    def set_password(self, name: str, password: str) -> None:
        """Set (or clear) the password for a profile. Empty string removes it."""
        meta = self._load_meta(name)
        if password:
            meta["password_hash"] = self._hash_password(password)
        else:
            meta.pop("password_hash", None)
        self._save_meta(name, meta)

    def verify_password(self, name: str, password: str) -> bool:
        """Check a password against the stored hash. Returns True if no password is set."""
        meta = self._load_meta(name)
        stored = meta.get("password_hash", "")
        if not stored:
            return True  # no password required
        return self._check_password(password, stored)

    # ── Pet API ───────────────────────────────────────────────────────────────

    def get_pet(self, name: str) -> str | None:
        """Return the pet_id assigned to a profile, or None if not set."""
        meta = self._load_meta(name)
        return meta.get("pet_id")

    def set_pet(self, name: str, pet_id: str | None) -> None:
        """Persist the chosen pet for a profile. ``None`` clears it."""
        meta = self._load_meta(name)
        if pet_id:
            meta["pet_id"] = pet_id
        else:
            meta.pop("pet_id", None)
        self._save_meta(name, meta)
