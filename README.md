# Amnezia Telegram Bot

Telegram bot MVP for issuing AmneziaWG client configs from inside an existing
Amnezia container.

The bot is intentionally small: it runs in the same environment as AmneziaWG,
calls the local provisioning script, and sends the generated `vpn://` URI back
to an allowed Telegram user.

## Current Architecture

```text
Telegram user
    |
    v
telegram_bot.py
    |
    v
create_client.py
    |
    v
AmneziaWG: awg0, awg0.conf, clientsTable, clients/
```

The bot must run where these AmneziaWG resources are available:

- `awg` binary
- active `awg0` interface
- `/opt/amnezia/awg/awg0.conf`
- `/opt/amnezia/awg/clientsTable`
- `/opt/amnezia/awg/clients/`

## Repository Layout

```text
bot/
  bot_core.py        # Testable bot/provisioning logic
  create_client.py   # Creates an AmneziaWG client and prints vpn:// URI
  script.py          # Compatibility wrapper for create_client.py
  telegram_bot.py    # Telegram command handlers and polling entrypoint
  requirements.txt   # Python dependencies
  README.md          # Short bot-specific notes

tests/
  test_bot_core.py   # Unit tests for bot_core.py
```

## Requirements

- Python 3.9+
- Running AmneziaWG container/environment
- `awg` available in `PATH`
- Telegram bot token from BotFather
- Telegram user IDs allowed to use the bot

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
```

Variables:

- `TELEGRAM_BOT_TOKEN`: token received from BotFather.
- `TELEGRAM_ADMIN_IDS`: comma-separated or space-separated Telegram user IDs.
- `AMNEZIA_PUBLIC_ENDPOINT`: public IP address or DNS name clients should use.

Optional overrides:

```sh
export AMNEZIA_CLIENTS_DIR="/opt/amnezia/awg/clients"
export AMNEZIA_CREATE_CLIENT_SCRIPT="/opt/amnezia/awg/bot/create_client.py"
```

## Install Inside the Amnezia Container

Copy the `bot/` directory into the Amnezia container. The default path expected
by the code is:

```text
/opt/amnezia/awg/bot/
```

Install dependencies:

```sh
python3 -m pip install -r /opt/amnezia/awg/bot/requirements.txt
```

Start the bot:

```sh
python3 /opt/amnezia/awg/bot/telegram_bot.py
```

## Telegram Commands

- `/start`: show available commands.
- `/help`: show available commands.
- `/status`: check whether the current Telegram user already has a VPN config.
- `/create`: create a VPN config for the current Telegram user.

Clients are named as:

```text
tg_<telegram_user_id>
```

Example:

```text
tg_123456789
```

## Provisioning Behavior

`create_client.py` performs the low-level AmneziaWG changes:

- reads `/opt/amnezia/awg/awg0.conf`
- allocates a free client IP address
- generates client keys with `awg`
- applies the peer to the live `awg0` interface
- writes `/opt/amnezia/awg/clients/<client_name>.conf`
- backs up and appends to `awg0.conf`
- updates `/opt/amnezia/awg/clientsTable`
- prints a `vpn://` URI to stdout

`telegram_bot.py` treats stdout from `create_client.py` as the VPN link.

If a config file already exists for the Telegram user, the bot does not
recreate it. It replies that the config already exists.

## Local Development

Run unit tests:

```sh
python3 -m unittest tests/test_bot_core.py
```

Compile-check Python files:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/amnezia_tg_pycache \
  python3 -m py_compile \
  bot/bot_core.py \
  bot/create_client.py \
  bot/script.py \
  bot/telegram_bot.py \
  tests/test_bot_core.py
```

The full provisioning flow cannot be tested on a local machine unless `awg`,
`awg0`, and the Amnezia config files are available.

## Security Notes

- Do not commit real Telegram bot tokens.
- Keep runtime secrets in environment variables.
- Restrict access with `TELEGRAM_ADMIN_IDS`.
- Run the bot only in a trusted Amnezia environment.
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

### `awg binary not found`

Run the bot inside the AmneziaWG environment where `awg` is installed and
available in `PATH`.

### `client config already exists`

The bot uses stable client names derived from Telegram user IDs. If
`/opt/amnezia/awg/clients/tg_<id>.conf` already exists, the bot will not create
a duplicate client.
