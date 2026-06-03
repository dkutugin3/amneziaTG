import tempfile
import unittest
from pathlib import Path

from bot.access_store import AccessStore


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


if __name__ == "__main__":
    unittest.main()
