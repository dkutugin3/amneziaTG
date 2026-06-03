# Amnezia Telegram Bot MVP

This bot is intended to run inside the same container/environment as AmneziaWG,
where `awg`, `awg0`, `/opt/amnezia/awg/awg0.conf`, and
`/opt/amnezia/awg/clientsTable` are available.

## Files

- `create_client.py` creates an AmneziaWG client and prints a `vpn://` URI.
- `telegram_bot.py` handles Telegram commands and calls `create_client.py`.
- `bot_core.py` contains testable bot/provisioning logic.

## Environment

Set these variables before starting the bot:

```sh
export TELEGRAM_BOT_TOKEN="123456:telegram-token"
export TELEGRAM_ADMIN_IDS="123456789,987654321"
export AMNEZIA_PUBLIC_ENDPOINT="vpn.example.com"
```

Optional overrides:

```sh
export AMNEZIA_CLIENTS_DIR="/opt/amnezia/awg/clients"
export AMNEZIA_CREATE_CLIENT_SCRIPT="/opt/amnezia/awg/bot/create_client.py"
```

## Install and Run

Inside the Amnezia container:

```sh
python3 -m pip install -r /opt/amnezia/awg/bot/requirements.txt
python3 /opt/amnezia/awg/bot/telegram_bot.py
```

## Telegram Commands

- `/start` shows the command list.
- `/help` shows the command list.
- `/status` checks whether the current Telegram user already has a config.
- `/create` creates a VPN config for the current Telegram user.

Clients are named as `tg_<telegram_user_id>`.
