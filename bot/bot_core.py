import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Set


DEFAULT_CLIENTS_DIR = Path("/opt/amnezia/awg/clients")
DEFAULT_CREATE_CLIENT_SCRIPT = Path("/opt/amnezia/awg/bot/create_client.py")
DEFAULT_DOCKER_BINARY = "docker"
LOCAL_MODE = "local"
DOCKER_EXEC_MODE = "docker-exec"


class CreateClientError(RuntimeError):
    """Raised when the provisioning script fails."""


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: Set[int]
    public_endpoint: str
    clients_dir: Path = DEFAULT_CLIENTS_DIR
    create_client_script: Path = DEFAULT_CREATE_CLIENT_SCRIPT
    provision_mode: str = LOCAL_MODE
    amnezia_container_name: Optional[str] = None
    docker_binary: str = DEFAULT_DOCKER_BINARY


@dataclass(frozen=True)
class CreateClientResult:
    client_name: str
    vpn_uri: Optional[str]
    already_exists: bool = False


Runner = Callable[[list[str]], subprocess.CompletedProcess]


def parse_admin_ids(raw: str) -> Set[int]:
    values = raw.replace(",", " ").split()
    ids: Set[int] = set()

    for value in values:
        try:
            ids.add(int(value))
        except ValueError as exc:
            raise ValueError(f"invalid Telegram user id: {value}") from exc

    return ids


def client_name_for_user(user_id: int) -> str:
    return f"tg_{user_id}"


def load_config_from_env() -> BotConfig:
    return load_config_from_mapping(os.environ)


def load_config_from_mapping(values: Mapping[str, str]) -> BotConfig:
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    public_endpoint = values.get("AMNEZIA_PUBLIC_ENDPOINT", "").strip()
    admin_ids = parse_admin_ids(values.get("TELEGRAM_ADMIN_IDS", ""))

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    if not public_endpoint:
        raise RuntimeError("AMNEZIA_PUBLIC_ENDPOINT is required")

    if not admin_ids:
        raise RuntimeError("TELEGRAM_ADMIN_IDS is required")

    provision_mode = values.get("AMNEZIA_PROVISION_MODE", LOCAL_MODE).strip()
    if provision_mode not in {LOCAL_MODE, DOCKER_EXEC_MODE}:
        raise RuntimeError(
            f"AMNEZIA_PROVISION_MODE must be {LOCAL_MODE!r} or {DOCKER_EXEC_MODE!r}"
        )

    amnezia_container_name = values.get("AMNEZIA_CONTAINER_NAME", "").strip() or None
    if provision_mode == DOCKER_EXEC_MODE and not amnezia_container_name:
        raise RuntimeError("AMNEZIA_CONTAINER_NAME is required in docker-exec mode")

    clients_dir = Path(values.get("AMNEZIA_CLIENTS_DIR", str(DEFAULT_CLIENTS_DIR)))
    script_path = Path(
        values.get("AMNEZIA_CREATE_CLIENT_SCRIPT", str(DEFAULT_CREATE_CLIENT_SCRIPT))
    )
    docker_binary = values.get("DOCKER_BINARY", DEFAULT_DOCKER_BINARY).strip()

    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        public_endpoint=public_endpoint,
        clients_dir=clients_dir,
        create_client_script=script_path,
        provision_mode=provision_mode,
        amnezia_container_name=amnezia_container_name,
        docker_binary=docker_binary,
    )


def default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True)


class Provisioner:
    def __init__(self, config: BotConfig, runner: Runner = default_runner):
        self.config = config
        self.runner = runner

    def is_allowed(self, user_id: int) -> bool:
        return user_id in self.config.admin_ids

    def client_exists(self, user_id: int) -> bool:
        client_name = client_name_for_user(user_id)
        if self.config.provision_mode == DOCKER_EXEC_MODE:
            result = self.runner([
                self.config.docker_binary,
                "exec",
                self._amnezia_container_name(),
                "test",
                "-f",
                str(self.config.clients_dir / f"{client_name}.conf"),
            ])
            return result.returncode == 0

        return (self.config.clients_dir / f"{client_name}.conf").exists()

    def create_client(self, user_id: int) -> CreateClientResult:
        client_name = client_name_for_user(user_id)

        if self.client_exists(user_id):
            return CreateClientResult(
                client_name=client_name,
                vpn_uri=None,
                already_exists=True,
            )

        command = self._create_client_command(client_name)
        result = self.runner(command)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "create client command failed").strip()
            raise CreateClientError(message)

        vpn_uri = result.stdout.strip()
        if not vpn_uri.startswith("vpn://"):
            raise CreateClientError("create client command did not return a vpn:// URI")

        return CreateClientResult(
            client_name=client_name,
            vpn_uri=vpn_uri,
            already_exists=False,
        )

    def _create_client_command(self, client_name: str) -> list[str]:
        command = [
            "python3",
            str(self.config.create_client_script),
            client_name,
            self.config.public_endpoint,
        ]

        if self.config.provision_mode == DOCKER_EXEC_MODE:
            return [
                self.config.docker_binary,
                "exec",
                self._amnezia_container_name(),
            ] + command

        return command

    def _amnezia_container_name(self) -> str:
        if not self.config.amnezia_container_name:
            raise RuntimeError("amnezia container name is not configured")
        return self.config.amnezia_container_name
