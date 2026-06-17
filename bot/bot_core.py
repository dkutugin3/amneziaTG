import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Set

try:
    from bot.access_store import AccessStore, DEFAULT_DB_PATH
except ImportError:
    from access_store import AccessStore, DEFAULT_DB_PATH


DEFAULT_CLIENTS_DIR = Path("/opt/amnezia/awg/clients")
DEFAULT_CREATE_CLIENT_SCRIPT = Path("/opt/amnezia/awg/bot/create_client.py")
DEFAULT_DOCKER_BINARY = "docker"
DEFAULT_SUBSCRIPTION_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
LOCAL_MODE = "local"
DOCKER_EXEC_MODE = "docker-exec"

DEFAULT_STAR_PRICING = {"7d": 25, "30d": 75, "90d": 200, "365d": 600}
DEFAULT_SUPPORT_CONTACT = "@your_support_username"
DEFAULT_TERMS_URL = ""


class CreateClientError(RuntimeError):
    """Raised when the provisioning script fails."""


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: Set[int]
    public_endpoint: str
    bot_username: Optional[str] = None
    clients_dir: Path = DEFAULT_CLIENTS_DIR
    create_client_script: Path = DEFAULT_CREATE_CLIENT_SCRIPT
    provision_mode: str = LOCAL_MODE
    amnezia_container_name: Optional[str] = None
    docker_binary: str = DEFAULT_DOCKER_BINARY
    db_path: Path = DEFAULT_DB_PATH
    subscription_check_interval_seconds: int = DEFAULT_SUBSCRIPTION_CHECK_INTERVAL_SECONDS
    star_pricing: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_STAR_PRICING))
    support_contact: str = DEFAULT_SUPPORT_CONTACT
    terms_url: Optional[str] = DEFAULT_TERMS_URL


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


def parse_star_pricing(raw: str) -> dict[str, int]:
    if not raw.strip():
        return dict(DEFAULT_STAR_PRICING)

    result: dict[str, int] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"invalid star pricing entry: {chunk!r}, expected '7d=25'")
        key, value = chunk.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        try:
            amount = int(value)
        except ValueError as exc:
            raise ValueError(f"invalid star amount: {value!r}") from exc
        if amount <= 0:
            raise ValueError(f"star amount must be greater than zero: {amount}")
        result[key] = amount

    if not result:
        return dict(DEFAULT_STAR_PRICING)
    return result


def client_name_for_user(user_id: int) -> str:
    return f"tg_{user_id}"


def load_config_from_env() -> BotConfig:
    return load_config_from_mapping(os.environ)


def load_config_from_mapping(values: Mapping[str, str]) -> BotConfig:
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    public_endpoint = values.get("AMNEZIA_PUBLIC_ENDPOINT", "").strip()
    bot_username = values.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@") or None
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
    db_path = Path(values.get("AMNEZIA_TG_DB_PATH", str(DEFAULT_DB_PATH)))
    subscription_check_interval_seconds = int(
        values.get(
            "SUBSCRIPTION_CHECK_INTERVAL_SECONDS",
            str(DEFAULT_SUBSCRIPTION_CHECK_INTERVAL_SECONDS),
        )
    )
    if subscription_check_interval_seconds <= 0:
        raise RuntimeError("SUBSCRIPTION_CHECK_INTERVAL_SECONDS must be greater than zero")

    star_pricing = parse_star_pricing(values.get("STAR_PRICING", ""))
    support_contact = values.get("SUPPORT_CONTACT", DEFAULT_SUPPORT_CONTACT).strip() or DEFAULT_SUPPORT_CONTACT
    terms_url = values.get("TERMS_URL", "").strip() or None

    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        public_endpoint=public_endpoint,
        bot_username=bot_username,
        clients_dir=clients_dir,
        create_client_script=script_path,
        provision_mode=provision_mode,
        amnezia_container_name=amnezia_container_name,
        docker_binary=docker_binary,
        db_path=db_path,
        subscription_check_interval_seconds=subscription_check_interval_seconds,
        star_pricing=star_pricing,
        support_contact=support_contact,
        terms_url=terms_url,
    )


def default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True)


class Provisioner:
    def __init__(
        self,
        config: BotConfig,
        runner: Runner = default_runner,
        access_store: Optional[AccessStore] = None,
    ):
        self.config = config
        self.runner = runner
        self.access_store = access_store

    def is_allowed(self, user_id: int) -> bool:
        if user_id in self.config.admin_ids:
            return True

        if self.access_store is None:
            return False

        return self.access_store.is_user_active(user_id)

    def is_admin(self, user_id: int) -> bool:
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

        if self.access_store is not None:
            self.access_store.record_client(user_id, client_name)

        return CreateClientResult(
            client_name=client_name,
            vpn_uri=vpn_uri,
            already_exists=False,
        )

    def get_client_config(self, user_id: int) -> str:
        client_name = client_name_for_user(user_id)

        if not self.client_exists(user_id):
            raise CreateClientError("client config not found, run /create first")

        command = self._regenerate_client_command(client_name)
        result = self.runner(command)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "regenerate client command failed").strip()
            raise CreateClientError(message)

        vpn_uri = result.stdout.strip()
        if not vpn_uri.startswith("vpn://"):
            raise CreateClientError("regenerate client command did not return a vpn:// URI")

        return vpn_uri

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

    def _regenerate_client_command(self, client_name: str) -> list[str]:
        command = [
            "python3",
            str(self.config.create_client_script),
            client_name,
            self.config.public_endpoint,
            "--regenerate",
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
