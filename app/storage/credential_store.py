from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

LOGGER = logging.getLogger(__name__)


class CredentialStore:
    """Encrypts and stores credentials in SQLite."""

    def __init__(self, db_path: Path, key: bytes) -> None:
        self.db_path = db_path
        self.fernet = Fernet(key)
        self._initialize()

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    provider TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def save(self, provider: str, payload: dict[str, Any]) -> None:
        encrypted = self.fernet.encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO credentials(provider, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider)
                DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (provider, encrypted, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def load(self, provider: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM credentials WHERE provider = ?",
                (provider,),
            ).fetchone()
        if not row:
            return None
        try:
            decrypted = self.fernet.decrypt(row[0].encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError):
            LOGGER.warning("Failed to decrypt credential payload for provider=%s", provider)
            return None
