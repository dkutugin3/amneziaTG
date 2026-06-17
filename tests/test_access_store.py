import tempfile
import unittest
from pathlib import Path

from bot.access_store import AccessStore, parse_subscription_duration


class AccessStoreTest(unittest.TestCase):
    def test_invite_key_redeem_binds_key_to_telegram_id_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")

            invite = store.create_invite("alice", created_by_tg_id=1)
            redeemed = store.redeem_invite(invite.key, tg_id=42)
            second_redeem = store.redeem_invite(invite.key, tg_id=43)

            self.assertEqual(invite.key, "AMZ-TEST-KEY")
            self.assertEqual(redeemed.status, "redeemed")
            self.assertEqual(second_redeem.status, "already_bound")
            self.assertTrue(store.is_user_active(42))
            self.assertFalse(store.is_user_active(43))

    def test_redeem_unknown_key_returns_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite")

            result = store.redeem_invite("NO-SUCH-KEY", tg_id=42)

            self.assertEqual(result.status, "invalid")
            self.assertFalse(store.is_user_active(42))

    def test_revoked_key_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")
            invite = store.create_invite("alice", created_by_tg_id=1)

            self.assertTrue(store.revoke_invite(invite.key))
            result = store.redeem_invite(invite.key, tg_id=42)

            self.assertEqual(result.status, "revoked")
            self.assertFalse(store.is_user_active(42))

    def test_revoking_bound_key_removes_user_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")
            invite = store.create_invite("alice", created_by_tg_id=1)
            store.redeem_invite(invite.key, tg_id=42)

            self.assertTrue(store.is_user_active(42))
            store.revoke_invite(invite.key)

            self.assertFalse(store.is_user_active(42))

    def test_revoke_user_removes_access_by_telegram_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")
            invite = store.create_invite("alice", created_by_tg_id=1)
            store.redeem_invite(invite.key, tg_id=42)

            self.assertTrue(store.revoke_user(42))

            self.assertFalse(store.is_user_active(42))

    def test_clients_are_recorded_by_telegram_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite")

            store.record_client(tg_id=42, client_name="tg_42")
            client = store.get_client(42)

            self.assertIsNotNone(client)
            self.assertEqual(client.client_name, "tg_42")

    def test_list_users_returns_bound_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")
            invite = store.create_invite("alice", created_by_tg_id=1)
            store.redeem_invite(invite.key, tg_id=42)

            users = store.list_users()

            self.assertEqual(len(users), 1)
            self.assertEqual(users[0].tg_id, 42)
            self.assertEqual(users[0].label, "alice")

    def test_list_broadcast_recipients_returns_only_active_users(self):
        keys = iter(["AMZ-TEST-KEY1", "AMZ-TEST-KEY2", "AMZ-TEST-KEY3"])
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: next(keys),
                clock=lambda: current_time,
            )
            active = store.create_invite("active", created_by_tg_id=1, duration="forever")
            expired = store.create_invite("expired", created_by_tg_id=1, duration="7d")
            revoked = store.create_invite("revoked", created_by_tg_id=1, duration="forever")
            store.redeem_invite(active.key, tg_id=42)
            store.redeem_invite(expired.key, tg_id=43)
            store.redeem_invite(revoked.key, tg_id=44)
            store.revoke_user(44)

            current_time = 605_801
            recipients = store.list_broadcast_recipients()

            self.assertEqual([item.tg_id for item in recipients], [42])

    def test_parse_subscription_duration_accepts_days_and_forever(self):
        self.assertEqual(parse_subscription_duration("7d"), 7 * 24 * 60 * 60)
        self.assertEqual(parse_subscription_duration("2w"), 14 * 24 * 60 * 60)
        self.assertEqual(parse_subscription_duration("1y"), 365 * 24 * 60 * 60)
        self.assertIsNone(parse_subscription_duration("forever"))

    def test_parse_subscription_duration_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            parse_subscription_duration("soon")

        with self.assertRaises(ValueError):
            parse_subscription_duration("0d")

    def test_timed_subscription_expires_and_blocks_access(self):
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: "AMZ-TEST-KEY",
                clock=lambda: current_time,
            )
            invite = store.create_invite("alice", created_by_tg_id=1, duration="7d")
            store.redeem_invite(invite.key, tg_id=42)

            self.assertTrue(store.is_user_active(42))
            self.assertEqual(store.get_subscription(42).expires_at, 605_800)

            current_time = 605_801

            self.assertFalse(store.is_user_active(42))
            self.assertEqual(store.get_subscription(42).status, "expired")

    def test_expired_invite_cannot_be_redeemed(self):
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: "AMZ-TEST-KEY",
                clock=lambda: current_time,
            )
            invite = store.create_invite("alice", created_by_tg_id=1, duration="7d")

            current_time = 605_801
            result = store.redeem_invite(invite.key, tg_id=42)

            self.assertEqual(result.status, "expired")
            self.assertFalse(store.is_user_active(42))

    def test_forever_subscription_never_expires(self):
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: "AMZ-TEST-KEY",
                clock=lambda: current_time,
            )
            invite = store.create_invite("alice", created_by_tg_id=1, duration="forever")
            store.redeem_invite(invite.key, tg_id=42)

            current_time = 999_999_999

            self.assertTrue(store.is_user_active(42))
            self.assertIsNone(store.get_subscription(42).expires_at)
            self.assertEqual(store.get_subscription(42).status, "active")

    def test_extend_user_from_existing_expiration_or_forever(self):
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: "AMZ-TEST-KEY",
                clock=lambda: current_time,
            )
            invite = store.create_invite("alice", created_by_tg_id=1, duration="7d")
            store.redeem_invite(invite.key, tg_id=42)

            updated = store.extend_user(42, "7d")

            self.assertTrue(updated)
            self.assertEqual(store.get_subscription(42).expires_at, 1_210_600)

            updated = store.extend_user(42, "forever")

            self.assertTrue(updated)
            self.assertIsNone(store.get_subscription(42).expires_at)

    def test_due_subscription_notifications_are_marked_once(self):
        current_time = 1_000
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(
                Path(tmp) / "db.sqlite",
                key_generator=lambda: "AMZ-TEST-KEY",
                clock=lambda: current_time,
            )
            invite = store.create_invite("alice", created_by_tg_id=1, duration="7d")
            store.redeem_invite(invite.key, tg_id=42)

            due = store.subscription_notifications_due()

            self.assertEqual(len(due), 1)
            self.assertEqual(due[0].tg_id, 42)
            self.assertEqual(due[0].days_left, 7)

            store.mark_subscription_notified(42, days_left=7)

            self.assertEqual(store.subscription_notifications_due(), [])


if __name__ == "__main__":
    unittest.main()
