# Amnezia Telegram Bot

Telegram bot MVP for issuing AmneziaWG client configs from a separate Docker
container.

The bot container uses Docker CLI access to execute the provisioning script
inside the existing Amnezia container. The low-level AmneziaWG changes still
happen inside the Amnezia environment where `awg`, `awg0`, `awg0.conf`, and
`clientsTable` are available.

## Current Architecture

```text
Telegram user
    |
    v
amnezia-tg-bot container
    |
    | docker exec <amnezia-container> python3 create_client.py ...
    v
Amnezia container
    |
    v
AmneziaWG: awg0, awg0.conf, clientsTable, clients/
```

The bot container does not need direct access to AmneziaWG files. It needs:

- Docker CLI
- mounted Docker socket: `/var/run/docker.sock`
- name of the Amnezia container

The provisioning script must exist inside the Amnezia container where these
resources are available:

- `awg` binary
- active `awg0` interface
- `/opt/amnezia/awg/awg0.conf`
- `/opt/amnezia/awg/clientsTable`
- `/opt/amnezia/awg/clients/`

## Repository Layout

```text
bot/
  access_store.py    # SQLite invite keys, user access, and client records
  bot_core.py        # Testable bot/provisioning logic
  create_client.py   # Creates an AmneziaWG client and prints vpn:// URI
  script.py          # Compatibility wrapper for create_client.py
  telegram_bot.py    # Telegram command handlers and polling entrypoint
  requirements.txt   # Python dependencies
  README.md          # Short bot-specific notes

tests/
  test_access_store.py
  test_bot_core.py   # Unit tests for bot_core.py

Dockerfile           # Bot container image
docker-compose.yml   # Bot service definition
.env.example         # Runtime configuration template
```

## Requirements

- Docker and Docker Compose
- Running AmneziaWG container
- `awg` available in `PATH` inside the Amnezia container
- Telegram bot token from BotFather
- Admin Telegram user IDs

Python dependency:

```text
python-telegram-bot==22.5
```

## Configuration

Set these environment variables before starting the bot:

```sh
export TELEGRAM_BOT_TOKEN="123456:telegram-token"
export TELEGRAM_ADMIN_IDS="123456789,987654321"
export AMNEZIA_PUBLIC_ENDPOINT="vpn.example.com"
export AMNEZIA_CONTAINER_NAME="amnezia-awg"
export AMNEZIA_TG_DB_PATH="/data/amnezia_tg.db"
```

Variables:

- `TELEGRAM_BOT_TOKEN`: token received from BotFather.
- `TELEGRAM_ADMIN_IDS`: comma-separated or space-separated Telegram user IDs.
- `AMNEZIA_PUBLIC_ENDPOINT`: public IP address or DNS name clients should use.
- `AMNEZIA_CONTAINER_NAME`: Docker container name of the running Amnezia
  container.
- `AMNEZIA_TG_DB_PATH`: SQLite database path for invite keys and user records.

Optional overrides:

```sh
export AMNEZIA_CLIENTS_DIR="/opt/amnezia/awg/clients"
export AMNEZIA_CREATE_CLIENT_SCRIPT="/opt/amnezia/awg/bot/create_client.py"
export DOCKER_BINARY="docker"
```

## Prepare the Amnezia Container

The bot runs separately, but `create_client.py` must be available inside the
Amnezia container. The default path expected by `docker-compose.yml` is:

```text
/opt/amnezia/awg/bot/create_client.py
```

Copy the provisioning script into the Amnezia container:

```sh
docker exec amnezia-awg mkdir -p /opt/amnezia/awg/bot
docker cp bot/create_client.py amnezia-awg:/opt/amnezia/awg/bot/create_client.py
```

Replace `amnezia-awg` with your actual Amnezia container name.

## Run the Bot Container

Create `.env` from the template:

```sh
cp .env.example .env
```

Edit `.env` and set real values:

```sh
TELEGRAM_BOT_TOKEN=123456:real-token
TELEGRAM_ADMIN_IDS=123456789
AMNEZIA_PUBLIC_ENDPOINT=vpn.example.com
AMNEZIA_CONTAINER_NAME=amnezia-awg
AMNEZIA_TG_DB_PATH=/data/amnezia_tg.db
```

Start the bot:

```sh
docker compose up -d --build
```

View logs:

```sh
docker compose logs -f amnezia-tg-bot
```

Stop the bot:

```sh
docker compose down
```

## Telegram Commands

Admin commands:

- `/key_create <name>`: create a one-time invite key for a friend.
- `/keys`: list invite labels, binding status, and revoked state.
- `/key_revoke <key>`: revoke an unused or already-bound key.
- `/user_revoke <tg_id>`: revoke access for an activated user.
- `/users`: list activated users.

User commands:

- `/redeem <key>`: activate access with a one-time invite key.
- `/status`: check access and VPN config status.
- `/create`: create a VPN config for the current Telegram user.
- `/start` and `/help`: show available commands.

Invite keys bind to the first Telegram ID that redeems them. A revoked key
removes access for the bound user.

Clients are named as:

```text
tg_<telegram_user_id>
```

Example:

```text
tg_123456789
```

## Provisioning Behavior

`telegram_bot.py` runs in the bot container. In `docker-exec` mode it calls:

```sh
docker exec <AMNEZIA_CONTAINER_NAME> \
  python3 /opt/amnezia/awg/bot/create_client.py \
  tg_<telegram_user_id> <AMNEZIA_PUBLIC_ENDPOINT>
```

`create_client.py` runs inside the Amnezia container and performs the low-level
AmneziaWG changes:

- reads `/opt/amnezia/awg/awg0.conf`
- allocates a free client IP address
- generates client keys with `awg`
- applies the peer to the live `awg0` interface
- writes `/opt/amnezia/awg/clients/<client_name>.conf`
- backs up and appends to `awg0.conf`
- updates `/opt/amnezia/awg/clientsTable`
- prints a `vpn://` URI to stdout

The bot treats stdout from `create_client.py` as the VPN link and records the
created client name in SQLite.

If a config file already exists for the Telegram user, the bot does not
recreate it. It replies that the config already exists.

## Local Development

Run unit tests:

```sh
python3 -m unittest tests/test_bot_core.py tests/test_access_store.py
```

Compile-check Python files:

```sh
PYTHONPYCACHEPREFIX=/tmp/pycache \
  python3 -m py_compile \
  bot/bot_core.py \
  bot/access_store.py \
  bot/create_client.py \
  bot/script.py \
  bot/telegram_bot.py \
  tests/test_access_store.py \
  tests/test_bot_core.py
```

The full provisioning flow requires a running Amnezia container and Docker
socket access.

## Security Notes

- Do not commit real Telegram bot tokens.
- Keep runtime secrets in environment variables.
- Restrict admin access with `TELEGRAM_ADMIN_IDS`.
- Invite keys are one-time keys and are stored as SHA-256 hashes, not plaintext.
- The bot container mounts `/var/run/docker.sock`. Treat this as privileged
  access to the Docker host.
- Run the bot only on a trusted server.
- `create_client.py` writes private client keys into generated config files.

## Troubleshooting

### `TELEGRAM_BOT_TOKEN is required`

Set `TELEGRAM_BOT_TOKEN` before starting `telegram_bot.py`.

### `TELEGRAM_ADMIN_IDS is required`

Set at least one allowed Telegram user ID:

```sh
export TELEGRAM_ADMIN_IDS="123456789"
```

### `AMNEZIA_PUBLIC_ENDPOINT is required`

Set the public address used by VPN clients:

```sh
export AMNEZIA_PUBLIC_ENDPOINT="1.2.3.4"
```

### `AMNEZIA_CONTAINER_NAME is required in docker-exec mode`

Set the Docker container name of the running Amnezia container:

```sh
export AMNEZIA_CONTAINER_NAME="amnezia-awg"
```

### `awg binary not found`

Make sure `create_client.py` is executed inside the Amnezia container and that
`awg` is installed there.

### `docker: not found`

Use the provided `Dockerfile`. It is based on Docker CLI image and includes the
Docker client required for `docker exec`.

### `Cannot connect to the Docker daemon`

Make sure the Docker socket is mounted:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

### `client config already exists`

The bot uses stable client names derived from Telegram user IDs. If
`/opt/amnezia/awg/clients/tg_<id>.conf` already exists, the bot will not create
a duplicate client.
