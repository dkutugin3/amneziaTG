import subprocess
import tempfile
import unittest
from pathlib import Path

from bot.bot_core import (
    BotConfig,
    CreateClientError,
    Provisioner,
    client_name_for_user,
    load_config_from_mapping,
    parse_admin_ids,
)
from bot.access_store import AccessStore


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

    def test_allowed_user_can_come_from_redeemed_invite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite", key_generator=lambda: "AMZ-TEST-KEY")
            invite = store.create_invite("alice", created_by_tg_id=1)
            store.redeem_invite(invite.key, tg_id=42)
            config = BotConfig(
                token="token",
                admin_ids={1},
                public_endpoint="vpn.example.com",
            )

            provisioner = Provisioner(config, access_store=store)

            self.assertTrue(provisioner.is_allowed(1))
            self.assertTrue(provisioner.is_allowed(42))
            self.assertFalse(provisioner.is_allowed(43))

    def test_create_records_client_after_successful_generation(self):
        def runner(command):
            return subprocess.CompletedProcess(command, 0, "vpn://abc\n", "")

        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "db.sqlite")
            config = BotConfig(
                token="token",
                admin_ids={42},
                public_endpoint="vpn.example.com",
                clients_dir=Path(tmp) / "clients",
                create_client_script=Path(tmp) / "create_client.py",
            )

            result = Provisioner(config, runner=runner, access_store=store).create_client(42)

            self.assertEqual(result.vpn_uri, "vpn://abc")
            self.assertEqual(store.get_client(42).client_name, "tg_42")

    def test_docker_exec_mode_checks_client_inside_amnezia_container(self):
        calls = []

        def runner(command):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        config = BotConfig(
            token="token",
            admin_ids={42},
            public_endpoint="vpn.example.com",
            provision_mode="docker-exec",
            amnezia_container_name="amnezia",
        )

        self.assertTrue(Provisioner(config, runner=runner).client_exists(42))
        self.assertEqual(
            calls,
            [
                [
                    "docker",
                    "exec",
                    "amnezia",
                    "test",
                    "-f",
                    "/opt/amnezia/awg/clients/tg_42.conf",
                ]
            ],
        )

    def test_docker_exec_mode_runs_create_script_inside_amnezia_container(self):
        calls = []

        def runner(command):
            calls.append(command)
            if command[3:5] == ["test", "-f"]:
                return subprocess.CompletedProcess(command, 1, "", "")
            return subprocess.CompletedProcess(command, 0, "vpn://abc\n", "")

        config = BotConfig(
            token="token",
            admin_ids={42},
            public_endpoint="vpn.example.com",
            provision_mode="docker-exec",
            amnezia_container_name="amnezia",
        )

        result = Provisioner(config, runner=runner).create_client(42)

        self.assertEqual(result.vpn_uri, "vpn://abc")
        self.assertEqual(
            calls[-1],
            [
                "docker",
                "exec",
                "amnezia",
                "python3",
                "/opt/amnezia/awg/bot/create_client.py",
                "tg_42",
                "vpn.example.com",
            ],
        )

    def test_load_config_from_mapping_supports_docker_exec_mode(self):
        config = load_config_from_mapping({
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ADMIN_IDS": "42",
            "AMNEZIA_PUBLIC_ENDPOINT": "vpn.example.com",
            "AMNEZIA_PROVISION_MODE": "docker-exec",
            "AMNEZIA_CONTAINER_NAME": "amnezia-awg",
        })

        self.assertEqual(config.provision_mode, "docker-exec")
        self.assertEqual(config.amnezia_container_name, "amnezia-awg")

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
