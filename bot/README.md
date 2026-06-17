# Amnezia Telegram Bot MVP

This directory contains the Telegram bot and the AmneziaWG provisioning script.
In the current Docker setup, the bot runs in its own container and executes
`create_client.py` inside the Amnezia container with `docker exec`.

## Files

- `create_client.py` creates an AmneziaWG client and prints a `vpn://` URI.
- `telegram_bot.py` handles Telegram commands.
- `bot_core.py` contains testable bot/provisioning logic.
- `access_store.py` stores invite keys, subscriptions, activated users, and
  client records.

## Environment

Set these variables before starting the bot:

```sh
export TELEGRAM_BOT_TOKEN="123456:telegram-token"
export TELEGRAM_ADMIN_IDS="123456789,987654321"
export AMNEZIA_PUBLIC_ENDPOINT="vpn.example.com"
export AMNEZIA_PROVISION_MODE="docker-exec"
export AMNEZIA_CONTAINER_NAME="amnezia-awg"
export AMNEZIA_TG_DB_PATH="/data/amnezia_tg.db"
export SUBSCRIPTION_CHECK_INTERVAL_SECONDS="86400"
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

The bot shows role-based Telegram buttons. Slash commands are still supported
as a fallback.

Admin commands:

- `Create invite` creates a one-time invite key with a subscription duration.
- `Invite keys` lists invite keys by label, binding status, and subscription
  status.
- `Extend user` extends a user's subscription or makes it permanent.
- `Broadcast` sends a mass announcement to all active users after confirmation.
- `Revoke key` revokes an invite key and its bound access.
- `Revoke user` revokes access for an activated user.
- `Users` lists activated users and subscription status.

User commands:

- `Activate access` binds an invite key to the current Telegram ID.
- `Status` checks access and config status.
- `Create config` creates a VPN config for the current Telegram user.
- `Report issue` sends a problem report to admins and works even before access
  activation.
- `Amnezia instructions` explains how to install Amnezia VPN and import the
  `vpn://` configuration string.
- `Help` shows available actions.

Duration examples: `7d`, `30d`, `90d`, `365d`, `2w`, `1m`, `1y`, `forever`.

Slash command examples:

```text
/key_create alice 30d
/key_create bob forever
/user_extend 123456789 90d
/user_extend 123456789 forever
/broadcast We will update the VPN server tonight at 23:00 UTC.
/report VPN does not connect after importing the config.
```

Broadcasts are delivered only to active users. Revoked and expired
subscriptions are skipped. The bot shows a preview and requires `Send broadcast`
before delivery.

Admins receive Telegram notifications when users redeem keys, check status,
create configs, when admins create/revoke/list access, and when subscriptions
are close to expiration. User reports are sent to all admins with Telegram
identity, access status, and the report text.

Clients are named as `tg_<telegram_user_id>`.
