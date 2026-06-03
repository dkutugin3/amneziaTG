import hashlib
import secrets
import sqlite3
import string
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


DEFAULT_DB_PATH = Path("/data/amnezia_tg.db")
KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Invite:
    key: str
    label: str


@dataclass(frozen=True)
class RedeemResult:
    status: str
    label: Optional[str] = None


@dataclass(frozen=True)
class ClientRecord:
    tg_id: int
    client_name: str


@dataclass(frozen=True)
class UserRecord:
    tg_id: int
    label: str
    client_name: Optional[str]
    revoked: bool


def normalize_key(key: str) -> str:
    return key.strip().upper()


def hash_key(key: str) -> str:
    return hashlib.sha256(normalize_key(key).encode("utf-8")).hexdigest()


def generate_invite_key() -> str:
    chars = "".join(secrets.choice(KEY_ALPHABET) for _ in range(12))
    return f"AMZ-{chars[:4]}-{chars[4:8]}-{chars[8:]}"


class AccessStore:
    def __init__(
        self,
        path: Path = DEFAULT_DB_PATH,
        key_generator: Callable[[], str] = generate_invite_key,
    ):
        self.path = Path(path)
        self.key_generator = key_generator
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_invite(self, label: str, created_by_tg_id: int) -> Invite:
        clean_label = label.strip() or "friend"

        for _ in range(5):
            key = normalize_key(self.key_generator())
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO invite_keys (
                            key_hash, label, created_by_tg_id, created_at
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (hash_key(key), clean_label, created_by_tg_id, now()),
                    )
                return Invite(key=key, label=clean_label)
            except sqlite3.IntegrityError:
                continue

        raise RuntimeError("could not generate a unique invite key")

    def redeem_invite(self, key: str, tg_id: int) -> RedeemResult:
        key_hash = hash_key(key)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT label, bound_tg_id, revoked_at
                FROM invite_keys
                WHERE key_hash = ?
                """,
                (key_hash,),
            ).fetchone()

            if row is None:
                return RedeemResult(status="invalid")

            if row["revoked_at"] is not None:
                return RedeemResult(status="revoked", label=row["label"])

            if row["bound_tg_id"] is not None:
                if int(row["bound_tg_id"]) == tg_id:
                    return RedeemResult(status="already_redeemed", label=row["label"])
                return RedeemResult(status="already_bound", label=row["label"])

            active = conn.execute(
                """
                SELECT 1
                FROM invite_keys
                WHERE bound_tg_id = ? AND revoked_at IS NULL
                LIMIT 1
                """,
                (tg_id,),
            ).fetchone()
            if active is not None:
                return RedeemResult(status="user_already_active")

            conn.execute(
                """
                UPDATE invite_keys
                SET bound_tg_id = ?, bound_at = ?
                WHERE key_hash = ?
                """,
                (tg_id, now(), key_hash),
            )

        return RedeemResult(status="redeemed", label=row["label"])

    def revoke_invite(self, key: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE invite_keys
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE key_hash = ?
                """,
                (now(), hash_key(key)),
            )
            return result.rowcount > 0

    def revoke_user(self, tg_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE invite_keys
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE bound_tg_id = ? AND revoked_at IS NULL
                """,
                (now(), tg_id),
            )
            return result.rowcount > 0

    def is_user_active(self, tg_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM invite_keys
                WHERE bound_tg_id = ? AND revoked_at IS NULL
                LIMIT 1
                """,
                (tg_id,),
            ).fetchone()
        return row is not None

    def record_client(self, tg_id: int, client_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clients (tg_id, client_name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET client_name = excluded.client_name
                """,
                (tg_id, client_name, now()),
            )

    def get_client(self, tg_id: int) -> Optional[ClientRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tg_id, client_name FROM clients WHERE tg_id = ?",
                (tg_id,),
            ).fetchone()

        if row is None:
            return None

        return ClientRecord(tg_id=int(row["tg_id"]), client_name=row["client_name"])

    def list_invites(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT invite_keys.bound_tg_id, invite_keys.label, invite_keys.revoked_at,
                       clients.client_name
                FROM invite_keys
                LEFT JOIN clients ON clients.tg_id = invite_keys.bound_tg_id
                ORDER BY invite_keys.created_at DESC
                """
            ).fetchall()

        records = []
        for row in rows:
            tg_id = row["bound_tg_id"]
            records.append(
                UserRecord(
                    tg_id=int(tg_id) if tg_id is not None else 0,
                    label=row["label"],
                    client_name=row["client_name"],
                    revoked=row["revoked_at"] is not None,
                )
            )
        return records

    def list_users(self) -> list[UserRecord]:
        return [item for item in self.list_invites() if item.tg_id != 0]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invite_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    created_by_tg_id INTEGER NOT NULL,
                    bound_tg_id INTEGER,
                    created_at INTEGER NOT NULL,
                    bound_at INTEGER,
                    revoked_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    tg_id INTEGER PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def now() -> int:
    return int(time.time())
