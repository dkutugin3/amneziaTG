#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path


DEFAULT_CONF_PATH = "/opt/amnezia/awg/awg0.conf"
DEFAULT_CLIENTS_TABLE_PATH = "/opt/amnezia/awg/clientsTable"
DEFAULT_IFACE = "awg0"
DEFAULT_OUT_DIR = "/opt/amnezia/awg/clients"


def run(cmd, input_text=None):
    result = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    return result.stdout.strip()


def check_client_name(name: str):
    if not re.match(r"^[a-zA-Z0-9_.-]+$", name):
        raise SystemExit("ERROR: invalid client name. Use only letters, digits, _, ., -")


def read_file(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"ERROR: config not found: {path}")
    return path.read_text()


def get_interface_block(conf_text: str) -> list[str]:
    result = []
    in_iface = False

    for line in conf_text.splitlines():
        stripped = line.strip()

        if stripped == "[Interface]":
            in_iface = True
            continue

        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[Interface]":
            in_iface = False

        if in_iface:
            result.append(line)

    return result


def get_interface_value(conf_text: str, key: str) -> str:
    for line in get_interface_block(conf_text):
        clean = line.strip()

        if clean.startswith("#"):
            clean = clean[1:].strip()

        if "=" not in clean:
            continue

        k, v = clean.split("=", 1)

        if k.strip() == key:
            return v.strip()

    return ""


def get_obfuscation_params(conf_text: str) -> dict[str, str]:
    keys = [
        "Jc", "Jmin", "Jmax",
        "S1", "S2", "S3", "S4",
        "H1", "H2", "H3", "H4",
        "I1", "I2", "I3", "I4", "I5",
    ]

    params = {}

    for line in get_interface_block(conf_text):
        clean = line.strip()

        # В Amnezia I1-I5 могут быть закомментированы:
        # # I1 = ...
        if clean.startswith("#"):
            clean = clean[1:].strip()

        if "=" not in clean:
            continue

        k, v = clean.split("=", 1)
        k = k.strip()
        v = v.strip()

        if k in keys:
            params[k] = v

    return params


def get_used_ips(conf_text: str) -> set[str]:
    used = set()

    for line in conf_text.splitlines():
        clean = line.strip()

        if not clean.startswith("AllowedIPs"):
            continue

        if "=" not in clean:
            continue

        _, value = clean.split("=", 1)
        first_ip = value.strip().split(",")[0].strip()
        ip = first_ip.split("/")[0].strip()

        if ip:
            used.add(ip)

    return used


def allocate_ip(server_address: str, used_ips: set[str]) -> str:
    server_ip = server_address.split("/")[0].strip()
    parts = server_ip.split(".")

    if len(parts) != 4:
        raise SystemExit(f"ERROR: unsupported server Address: {server_address}")

    prefix = ".".join(parts[:3])

    for i in range(2, 255):
        candidate = f"{prefix}.{i}"

        if candidate == server_ip:
            continue

        if candidate not in used_ips:
            return candidate

    raise SystemExit(f"ERROR: no free IPs in {prefix}.0/24")


def endpoint_with_port(endpoint_host: str, listen_port: str) -> str:
    endpoint_host = endpoint_host.strip()

    # Уже готовый IPv6 endpoint: [2001:db8::1]:39983
    if endpoint_host.startswith("[") and "]:" in endpoint_host:
        return endpoint_host

    # IPv4/domain с портом: 1.2.3.4:39983 или example.com:39983
    if endpoint_host.count(":") == 1:
        return endpoint_host

    # IPv6 без порта
    if endpoint_host.count(":") > 1:
        return f"[{endpoint_host}]:{listen_port}"

    # IPv4/domain без порта
    return f"{endpoint_host}:{listen_port}"


def split_endpoint(endpoint: str) -> tuple[str, int]:
    endpoint = endpoint.strip()

    m = re.match(r"^\[(.+)\]:(\d+)$", endpoint)
    if m:
        return m.group(1), int(m.group(2))

    if ":" not in endpoint:
        raise SystemExit(f"ERROR: endpoint has no port: {endpoint}")

    host, port = endpoint.rsplit(":", 1)
    return host, int(port)


def encode_vpn_uri(obj: dict) -> str:
    # Amnezia vpn:// = qCompress(JSON) в urlsafe base64 без padding.
    # qCompress = 4 bytes raw length big-endian + zlib-compressed data.
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw)
    header = len(raw).to_bytes(4, byteorder="big")
    encoded = base64.urlsafe_b64encode(header + compressed).decode("ascii").rstrip("=")
    return "vpn://" + encoded


def build_client_conf(
    client_private_key: str,
    client_ip: str,
    dns: str,
    obfuscation: dict[str, str],
    server_public_key: str,
    preshared_key: str,
    endpoint: str,
) -> str:
    lines = [
        "[Interface]",
        f"PrivateKey = {client_private_key}",
        f"Address = {client_ip}/32",
        f"DNS = {dns}",
    ]

    for key in [
        "Jc", "Jmin", "Jmax",
        "S1", "S2", "S3", "S4",
        "H1", "H2", "H3", "H4",
        "I1", "I2", "I3", "I4", "I5",
    ]:
        if key in obfuscation:
            lines.append(f"{key} = {obfuscation[key]}")

    lines += [
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        f"PresharedKey = {preshared_key}",
        f"Endpoint = {endpoint}",
        "AllowedIPs = 0.0.0.0/0, ::/0",
        "PersistentKeepalive = 25",
        "",
    ]

    return "\n".join(lines)


def build_amnezia_json(
    client_name: str,
    client_conf_text: str,
    client_private_key: str,
    client_public_key: str,
    client_ip: str,
    dns: str,
    obfuscation: dict[str, str],
    server_public_key: str,
    preshared_key: str,
    endpoint: str,
) -> dict:
    host, port = split_endpoint(endpoint)

    awg_last_config = {
        "config": client_conf_text.replace("\r\n", "\n").replace("\n", "\r\n"),
        "hostName": host,
        "port": port,

        "client_ip": f"{client_ip}/32",
        "client_priv_key": client_private_key,
        "client_pub_key": client_public_key,
        "server_pub_key": server_public_key,
        "psk_key": preshared_key,
        "clientId": client_public_key,

        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "persistent_keep_alive": "25",
        "mtu": "1280",
        "isObfuscationEnabled": True,

        "Jc": obfuscation.get("Jc", ""),
        "Jmin": obfuscation.get("Jmin", ""),
        "Jmax": obfuscation.get("Jmax", ""),
        "S1": obfuscation.get("S1", ""),
        "S2": obfuscation.get("S2", ""),
        "S3": obfuscation.get("S3", ""),
        "S4": obfuscation.get("S4", ""),
        "H1": obfuscation.get("H1", ""),
        "H2": obfuscation.get("H2", ""),
        "H3": obfuscation.get("H3", ""),
        "H4": obfuscation.get("H4", ""),
        "I1": obfuscation.get("I1", ""),
        "I2": obfuscation.get("I2", ""),
        "I3": obfuscation.get("I3", ""),
        "I4": obfuscation.get("I4", ""),
        "I5": obfuscation.get("I5", ""),
    }

    return {
        "containers": [
            {
                "container": "amnezia-awg2",
                "awg": {
                    "protocol_version": "2",
                    "isThirdPartyConfig": True,
                    "port": str(port),
                    "transport_proto": "udp",

                    "Jc": obfuscation.get("Jc", ""),
                    "Jmin": obfuscation.get("Jmin", ""),
                    "Jmax": obfuscation.get("Jmax", ""),
                    "S1": obfuscation.get("S1", ""),
                    "S2": obfuscation.get("S2", ""),
                    "S3": obfuscation.get("S3", ""),
                    "S4": obfuscation.get("S4", ""),
                    "H1": obfuscation.get("H1", ""),
                    "H2": obfuscation.get("H2", ""),
                    "H3": obfuscation.get("H3", ""),
                    "H4": obfuscation.get("H4", ""),
                    "I1": obfuscation.get("I1", ""),
                    "I2": obfuscation.get("I2", ""),
                    "I3": obfuscation.get("I3", ""),
                    "I4": obfuscation.get("I4", ""),
                    "I5": obfuscation.get("I5", ""),

                    "last_config": json.dumps(
                        awg_last_config,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
        ],
        "defaultContainer": "amnezia-awg2",
        "description": client_name,
        "hostName": host,
        "dns1": dns,
        "dns2": "1.0.0.1",
    }


def build_vpn_uri(*args, **kwargs) -> str:
    return encode_vpn_uri(build_amnezia_json(*args, **kwargs))


def load_clients_table(path: Path):
    if not path.exists():
        return []

    raw = path.read_text().strip()

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        backup_path = path.with_name(path.name + f".invalid.bak.{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup_path)
        print(
            f"WARNING: invalid clientsTable JSON, backup created: {backup_path}",
            file=sys.stderr,
        )
        return []

    # Старый формат мог быть object:
    # {
    #   "client_public_key": { "clientName": "..." }
    # }
    if isinstance(data, dict):
        migrated = []

        for client_id, value in data.items():
            user_data = value if isinstance(value, dict) else {}
            migrated.append({
                "clientId": client_id,
                "userData": user_data,
            })

        return migrated

    if isinstance(data, list):
        normalized = []

        for item in data:
            if isinstance(item, dict):
                normalized.append(item)

        return normalized

    return []


def atomic_write_text(path: Path, text: str, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)

        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)

    finally:
        try:
            os.remove(tmp_name)
        except FileNotFoundError:
            pass


def update_clients_table(
    clients_table_path: Path,
    client_name: str,
    client_public_key: str,
    client_ip: str,
):
    clients = load_clients_table(clients_table_path)

    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    for item in clients:
        if not isinstance(item, dict):
            continue

        if item.get("clientId") == client_public_key:
            user_data = item.get("userData", {})
            if not isinstance(user_data, dict):
                user_data = {}

            user_data["clientName"] = client_name
            user_data.setdefault("creationDate", now)
            user_data["allowed_ips"] = f"{client_ip}/32"

            item["userData"] = user_data

            atomic_write_text(
                clients_table_path,
                json.dumps(clients, ensure_ascii=False, indent=4) + "\n",
                0o600,
            )
            return

    clients.append({
        "clientId": client_public_key,
        "userData": {
            "clientName": client_name,
            "creationDate": now,
            "allowed_ips": f"{client_ip}/32",
        },
    })

    atomic_write_text(
        clients_table_path,
        json.dumps(clients, ensure_ascii=False, indent=4) + "\n",
        0o600,
    )


class FileLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        while True:
            try:
                self.path.mkdir()
                return self
            except FileExistsError:
                time.sleep(0.2)

    def __exit__(self, exc_type, exc, tb):
        try:
            self.path.rmdir()
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Create AmneziaWG2 client, register it in clientsTable, and print vpn:// URI"
    )

    parser.add_argument("client_name", help="Client name, for example tg_123456789")
    parser.add_argument("endpoint_host", help="Public IP/domain, for example 1.2.3.4")

    parser.add_argument("--dns", default="1.1.1.1")
    parser.add_argument("--conf-path", default=DEFAULT_CONF_PATH)
    parser.add_argument("--clients-table-path", default=DEFAULT_CLIENTS_TABLE_PATH)
    parser.add_argument("--iface", default=DEFAULT_IFACE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)

    parser.add_argument("--print-conf-path", action="store_true")
    parser.add_argument("--print-conf", action="store_true")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--print-client-public-key", action="store_true")

    args = parser.parse_args()

    check_client_name(args.client_name)

    conf_path = Path(args.conf_path)
    clients_table_path = Path(args.clients_table_path)
    out_dir = Path(args.out_dir)
    lock_path = Path("/tmp/create-amnezia-client-uri.lock")

    awg_bin = shutil.which("awg")
    if not awg_bin:
        raise SystemExit("ERROR: awg binary not found")

    out_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)

    with FileLock(lock_path):
        conf_text = read_file(conf_path)

        listen_port = get_interface_value(conf_text, "ListenPort")
        server_address = get_interface_value(conf_text, "Address")

        if not listen_port:
            raise SystemExit("ERROR: ListenPort not found in [Interface]")

        if not server_address:
            raise SystemExit("ERROR: Address not found in [Interface]")

        try:
            server_public_key = run([awg_bin, "show", args.iface, "public-key"])
        except RuntimeError as e:
            raise SystemExit(
                f"ERROR: cannot get server public key from interface {args.iface}\n{e}"
            )

        if not server_public_key:
            raise SystemExit(f"ERROR: empty server public key from {args.iface}")

        client_conf_path = out_dir / f"{args.client_name}.conf"

        if client_conf_path.exists():
            raise SystemExit(f"ERROR: client config already exists: {client_conf_path}")

        if re.search(rf"^# Client: {re.escape(args.client_name)}$", conf_text, re.M):
            raise SystemExit(f"ERROR: client already exists in server config: {args.client_name}")

        used_ips = get_used_ips(conf_text)
        client_ip = allocate_ip(server_address, used_ips)

        endpoint = endpoint_with_port(args.endpoint_host, listen_port)
        obfuscation = get_obfuscation_params(conf_text)

        required_awg2_keys = ["S3", "S4", "I1"]
        missing = [k for k in required_awg2_keys if k not in obfuscation]

        if missing:
            print(
                f"WARNING: missing AWG2 params in server config: {', '.join(missing)}",
                file=sys.stderr,
            )

        client_private_key = run([awg_bin, "genkey"])
        client_public_key = run([awg_bin, "pubkey"], input_text=client_private_key + "\n")
        preshared_key = run([awg_bin, "genpsk"])

        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            psk_path = f.name
            f.write(preshared_key + "\n")

        os.chmod(psk_path, 0o600)

        try:
            run([
                awg_bin,
                "set",
                args.iface,
                "peer",
                client_public_key,
                "preshared-key",
                psk_path,
                "allowed-ips",
                f"{client_ip}/32",
            ])
        finally:
            try:
                os.remove(psk_path)
            except FileNotFoundError:
                pass

        client_conf_text = build_client_conf(
            client_private_key=client_private_key,
            client_ip=client_ip,
            dns=args.dns,
            obfuscation=obfuscation,
            server_public_key=server_public_key,
            preshared_key=preshared_key,
            endpoint=endpoint,
        )

        atomic_write_text(client_conf_path, client_conf_text, 0o600)

        conf_backup_path = conf_path.with_name(
            conf_path.name + f".bak.{time.strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.copy2(conf_path, conf_backup_path)

        if clients_table_path.exists():
            clients_table_backup_path = clients_table_path.with_name(
                clients_table_path.name + f".bak.{time.strftime('%Y%m%d-%H%M%S')}"
            )
            shutil.copy2(clients_table_path, clients_table_backup_path)

        peer_block = (
            f"\n"
            f"# Client: {args.client_name}\n"
            f"# CreatedAt: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
            f"[Peer]\n"
            f"PublicKey = {client_public_key}\n"
            f"PresharedKey = {preshared_key}\n"
            f"AllowedIPs = {client_ip}/32\n"
        )

        with conf_path.open("a") as f:
            f.write(peer_block)

        update_clients_table(
            clients_table_path=clients_table_path,
            client_name=args.client_name,
            client_public_key=client_public_key,
            client_ip=client_ip,
        )

        amnezia_json = build_amnezia_json(
            client_name=args.client_name,
            client_conf_text=client_conf_text,
            client_private_key=client_private_key,
            client_public_key=client_public_key,
            client_ip=client_ip,
            dns=args.dns,
            obfuscation=obfuscation,
            server_public_key=server_public_key,
            preshared_key=preshared_key,
            endpoint=endpoint,
        )

        vpn_uri = encode_vpn_uri(amnezia_json)

    if args.print_conf_path:
        print(client_conf_path)
    elif args.print_conf:
        print(client_conf_text)
    elif args.print_json:
        print(json.dumps(amnezia_json, ensure_ascii=False, indent=4))
    elif args.print_client_public_key:
        print(client_public_key)
    else:
        print(vpn_uri)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
