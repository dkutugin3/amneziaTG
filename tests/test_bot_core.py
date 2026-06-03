import subprocess
import tempfile
import unittest
from pathlib import Path

from bot.bot_core import (
    BotConfig,
    CreateClientError,
    Provisioner,
    client_name_for_user,
    parse_admin_ids,
)


class BotCoreTest(unittest.TestCase):
    def test_parse_admin_ids_accepts_commas_and_spaces(self):
        self.assertEqual(parse_admin_ids("123, 456 789"), {123, 456, 789})

    def test_parse_admin_ids_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            parse_admin_ids("123,abc")

    def test_client_name_is_stable_and_safe(self):
        self.assertEqual(client_name_for_user(123456789), "tg_123456789")

    def test_create_returns_existing_without_running_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            clients_dir = Path(tmp)
            (clients_dir / "tg_42.conf").write_text("[Interface]\n")
            config = BotConfig(
                token="token",
                admin_ids={42},
                public_endpoint="vpn.example.com",
                clients_dir=clients_dir,
                create_client_script=Path("/unused/create_client.py"),
            )

            provisioner = Provisioner(config, runner=self.fail_runner)
            result = provisioner.create_client(42)

            self.assertTrue(result.already_exists)
            self.assertEqual(result.client_name, "tg_42")
            self.assertIsNone(result.vpn_uri)

    def test_create_runs_script_and_returns_vpn_uri(self):
        calls = []

        def runner(command):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "vpn://abc\n", "")

        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "create_client.py"
            config = BotConfig(
                token="token",
                admin_ids={42},
                public_endpoint="vpn.example.com",
                clients_dir=Path(tmp) / "clients",
                create_client_script=script_path,
            )

            result = Provisioner(config, runner=runner).create_client(42)

        self.assertFalse(result.already_exists)
        self.assertEqual(result.vpn_uri, "vpn://abc")
        self.assertEqual(calls, [["python3", str(script_path), "tg_42", "vpn.example.com"]])

    def test_create_raises_safe_error_when_script_fails(self):
        def runner(command):
            return subprocess.CompletedProcess(command, 1, "", "ERROR: awg binary not found\n")

        with tempfile.TemporaryDirectory() as tmp:
            config = BotConfig(
                token="token",
                admin_ids={42},
                public_endpoint="vpn.example.com",
                clients_dir=Path(tmp) / "clients",
                create_client_script=Path(tmp) / "create_client.py",
            )

            with self.assertRaises(CreateClientError) as ctx:
                Provisioner(config, runner=runner).create_client(42)

        self.assertIn("awg binary not found", str(ctx.exception))

    @staticmethod
    def fail_runner(command):
        raise AssertionError(f"runner should not be called: {command}")


if __name__ == "__main__":
    unittest.main()
