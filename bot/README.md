# Amnezia Telegram Bot MVP

This directory contains the Telegram bot and the AmneziaWG provisioning script.
In the current Docker setup, the bot runs in its own container and executes
`create_client.py` inside the Amnezia container with `docker exec`.

## Files

- `create_client.py` creates an AmneziaWG client and prints a `vpn://` URI.
- `telegram_bot.py` handles Telegram commands.
- `bot_core.py` contains testable bot/provisioning logic.

## Environment

Set these variables before starting the bot:

```sh
export TELEGRAM_BOT_TOKEN="123456:telegram-token"
export TELEGRAM_ADMIN_IDS="123456789,987654321"
export AMNEZIA_PUBLIC_ENDPOINT="vpn.example.com"
export AMNEZIA_PROVISION_MODE="docker-exec"
export AMNEZIA_CONTAINER_NAME="amnezia-awg"
```

Optional overrides:

```sh
export AMNEZIA_CLIENTS_DIR="/opt/amnezia/awg/clients"
export AMNEZIA_CREATE_CLIENT_SCRIPT="/opt/amnezia/awg/bot/create_client.py"
export DOCKER_BINARY="docker"
```

## Install and Run with Docker Compose

From the repository root:

```sh
cp .env.example .env
docker exec amnezia-awg mkdir -p /opt/amnezia/awg/bot
docker cp bot/create_client.py amnezia-awg:/opt/amnezia/awg/bot/create_client.py
docker compose up -d --build
```

Replace `amnezia-awg` with the real Amnezia container name.

## Telegram Commands

- `/start` shows the command list.
- `/help` shows the command list.
- `/status` checks whether the current Telegram user already has a config.
- `/create` creates a VPN config for the current Telegram user.

Clients are named as `tg_<telegram_user_id>`.
