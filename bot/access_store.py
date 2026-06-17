import hashlib
import re
import secrets
import sqlite3
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
    expires_at: Optional[int] = None


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
    expires_at: Optional[int] = None
    status: str = "active"


@dataclass(frozen=True)
class SubscriptionRecord:
    tg_id: int
    label: str
    expires_at: Optional[int]
    revoked: bool
    status: str


@dataclass(frozen=True)
class SubscriptionNotification:
    tg_id: int
    label: str
    expires_at: int
    days_left: int


@dataclass(frozen=True)
class StarPaymentRecord:
    payment_id: int
    tg_id: int
    telegram_payment_charge_id: str
    duration: str
    stars: int
    created_at: int
    refunded: bool = False


def normalize_key(key: str) -> str:
    return key.strip().upper()


def hash_key(key: str) -> str:
    return hashlib.sha256(normalize_key(key).encode("utf-8")).hexdigest()


def generate_invite_key() -> str:
    chars = "".join(secrets.choice(KEY_ALPHABET) for _ in range(12))
    return f"AMZ-{chars[:4]}-{chars[4:8]}-{chars[8:]}"


def parse_subscription_duration(raw: str) -> Optional[int]:
    value = raw.strip().lower()
    if value in {"forever", "permanent", "infinite", "inf", "бессрочно"}:
        return None

    match = re.fullmatch(r"(\d+)\s*([dwmy])", value)
    if match is None:
        raise ValueError("duration must be like 7d, 2w, 1m, 1y, or forever")

    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("duration must be greater than zero")

    unit_seconds = {
        "d": 24 * 60 * 60,
        "w": 7 * 24 * 60 * 60,
        "m": 30 * 24 * 60 * 60,
        "y": 365 * 24 * 60 * 60,
    }
    return amount * unit_seconds[match.group(2)]


class AccessStore:
    def __init__(
        self,
        path: Path = DEFAULT_DB_PATH,
        key_generator: Callable[[], str] = generate_invite_key,
        clock: Optional[Callable[[], int]] = None,
    ):
        self.path = Path(path)
        self.key_generator = key_generator
        self.clock = clock or now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def create_invite(
        self,
        label: str,
        created_by_tg_id: int,
        duration: str = "forever",
    ) -> Invite:
        clean_label = label.strip() or "friend"
        duration_seconds = parse_subscription_duration(duration)
        expires_at = None
        if duration_seconds is not None:
            expires_at = self.clock() + duration_seconds

        for _ in range(5):
            key = normalize_key(self.key_generator())
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO invite_keys (
                            key_hash, label, created_by_tg_id, created_at, expires_at
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (hash_key(key), clean_label, created_by_tg_id, self.clock(), expires_at),
                    )
                return Invite(key=key, label=clean_label, expires_at=expires_at)
            except sqlite3.IntegrityError:
                continue

        raise RuntimeError("could not generate a unique invite key")

    def redeem_invite(self, key: str, tg_id: int) -> RedeemResult:
        key_hash = hash_key(key)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT label, bound_tg_id, revoked_at, expires_at
                FROM invite_keys
                WHERE key_hash = ?
                """,
                (key_hash,),
            ).fetchone()

            if row is None:
                return RedeemResult(status="invalid")

            if row["revoked_at"] is not None:
                return RedeemResult(status="revoked", label=row["label"])

            if row["expires_at"] is not None and int(row["expires_at"]) <= self.clock():
                return RedeemResult(status="expired", label=row["label"])

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
                (tg_id, self.clock(), key_hash),
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
                (self.clock(), hash_key(key)),
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
                (self.clock(), tg_id),
            )
            return result.rowcount > 0

    def is_user_active(self, tg_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM invite_keys
                WHERE bound_tg_id = ?
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (tg_id, self.clock()),
            ).fetchone()
        return row is not None

    def get_subscription(self, tg_id: int) -> Optional[SubscriptionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT bound_tg_id, label, expires_at, revoked_at
                FROM invite_keys
                WHERE bound_tg_id = ?
                ORDER BY bound_at DESC
                LIMIT 1
                """,
                (tg_id,),
            ).fetchone()

        if row is None:
            return None

        revoked = row["revoked_at"] is not None
        expires_at = row["expires_at"]
        return SubscriptionRecord(
            tg_id=int(row["bound_tg_id"]),
            label=row["label"],
            expires_at=int(expires_at) if expires_at is not None else None,
            revoked=revoked,
            status=self._subscription_status(revoked, expires_at),
        )

    def extend_user(self, tg_id: int, duration: str) -> bool:
        duration_seconds = parse_subscription_duration(duration)

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, expires_at
                FROM invite_keys
                WHERE bound_tg_id = ? AND revoked_at IS NULL
                ORDER BY bound_at DESC
                LIMIT 1
                """,
                (tg_id,),
            ).fetchone()
            if row is None:
                return False

            if duration_seconds is None:
                expires_at = None
            else:
                current_expires_at = row["expires_at"]
                base = self.clock()
                if current_expires_at is not None and int(current_expires_at) > base:
                    base = int(current_expires_at)
                expires_at = base + duration_seconds

            conn.execute(
                """
                UPDATE invite_keys
                SET expires_at = ?, notified_7d_at = NULL, notified_1d_at = NULL
                WHERE id = ?
                """,
                (expires_at, row["id"]),
            )
        return True

    def record_client(self, tg_id: int, client_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clients (tg_id, client_name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET client_name = excluded.client_name
                """,
                (tg_id, client_name, self.clock()),
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
                       invite_keys.expires_at,
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
                    expires_at=int(row["expires_at"]) if row["expires_at"] is not None else None,
                    status=self._subscription_status(
                        row["revoked_at"] is not None,
                        row["expires_at"],
                    ),
                )
            )
        return records

    def list_users(self) -> list[UserRecord]:
        return [item for item in self.list_invites() if item.tg_id != 0]

    def list_broadcast_recipients(self) -> list[UserRecord]:
        return [
            item
            for item in self.list_users()
            if item.status == "active" and not item.revoked
        ]

    def subscription_notifications_due(self) -> list[SubscriptionNotification]:
        current_time = self.clock()
        day_seconds = 24 * 60 * 60
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT bound_tg_id, label, expires_at, notified_7d_at, notified_1d_at
                FROM invite_keys
                WHERE bound_tg_id IS NOT NULL
                  AND revoked_at IS NULL
                  AND expires_at IS NOT NULL
                  AND expires_at > ?
                ORDER BY expires_at ASC
                """,
                (current_time,),
            ).fetchall()

        due: list[SubscriptionNotification] = []
        for row in rows:
            seconds_left = int(row["expires_at"]) - current_time
            if seconds_left <= day_seconds and row["notified_1d_at"] is None:
                days_left = 1
            elif seconds_left <= 7 * day_seconds and row["notified_7d_at"] is None:
                days_left = 7
            else:
                continue

            due.append(
                SubscriptionNotification(
                    tg_id=int(row["bound_tg_id"]),
                    label=row["label"],
                    expires_at=int(row["expires_at"]),
                    days_left=days_left,
                )
            )
        return due

    def mark_subscription_notified(self, tg_id: int, days_left: int) -> None:
        if days_left == 7:
            column = "notified_7d_at"
        elif days_left == 1:
            column = "notified_1d_at"
        else:
            raise ValueError("days_left must be 7 or 1")

        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE invite_keys
                SET {column} = ?
                WHERE bound_tg_id = ? AND revoked_at IS NULL
                """,
                (self.clock(), tg_id),
            )

    def record_star_payment(
        self,
        tg_id: int,
        telegram_payment_charge_id: str,
        duration: str,
        stars: int,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO star_payments (
                    tg_id, telegram_payment_charge_id, duration, stars, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (tg_id, telegram_payment_charge_id, duration, stars, self.clock()),
            )
            return int(cursor.lastrowid)

    def get_star_payment_by_charge_id(
        self,
        telegram_payment_charge_id: str,
    ) -> Optional[StarPaymentRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, tg_id, telegram_payment_charge_id, duration, stars,
                       created_at, refunded_at
                FROM star_payments
                WHERE telegram_payment_charge_id = ?
                """,
                (telegram_payment_charge_id,),
            ).fetchone()

        if row is None:
            return None

        return StarPaymentRecord(
            payment_id=int(row["id"]),
            tg_id=int(row["tg_id"]),
            telegram_payment_charge_id=row["telegram_payment_charge_id"],
            duration=row["duration"],
            stars=int(row["stars"]),
            created_at=int(row["created_at"]),
            refunded=row["refunded_at"] is not None,
        )

    def mark_star_payment_refunded(self, telegram_payment_charge_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE star_payments
                SET refunded_at = COALESCE(refunded_at, ?)
                WHERE telegram_payment_charge_id = ? AND refunded_at IS NULL
                """,
                (self.clock(), telegram_payment_charge_id),
            )
            return result.rowcount > 0

    def list_star_payments(self, limit: int = 50) -> list[StarPaymentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, tg_id, telegram_payment_charge_id, duration, stars,
                       created_at, refunded_at
                FROM star_payments
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            StarPaymentRecord(
                payment_id=int(row["id"]),
                tg_id=int(row["tg_id"]),
                telegram_payment_charge_id=row["telegram_payment_charge_id"],
                duration=row["duration"],
                stars=int(row["stars"]),
                created_at=int(row["created_at"]),
                refunded=row["refunded_at"] is not None,
            )
            for row in rows
        ]

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
                    revoked_at INTEGER,
                    expires_at INTEGER,
                    notified_7d_at INTEGER,
                    notified_1d_at INTEGER
                )
                """
            )
            self._ensure_column(conn, "invite_keys", "expires_at", "INTEGER")
            self._ensure_column(conn, "invite_keys", "notified_7d_at", "INTEGER")
            self._ensure_column(conn, "invite_keys", "notified_1d_at", "INTEGER")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    tg_id INTEGER PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS star_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_id INTEGER NOT NULL,
                    telegram_payment_charge_id TEXT NOT NULL UNIQUE,
                    duration TEXT NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    refunded_at INTEGER
                )
                """
            )

    def _subscription_status(self, revoked: bool, expires_at: Optional[int]) -> str:
        if revoked:
            return "revoked"
        if expires_at is not None and int(expires_at) <= self.clock():
            return "expired"
        return "active"

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        column_type: str,
    ) -> None:
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def now() -> int:
    return int(time.time())
