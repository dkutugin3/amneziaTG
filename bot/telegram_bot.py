#!/usr/bin/env python3
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot_core import Provisioner, load_config_from_env


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _user_id(update: Update) -> Optional[int]:
    if update.effective_user is None:
        return None
    return update.effective_user.id


async def _reply(update: Update, text: str) -> None:
    if update.message is not None:
        await update.message.reply_text(text)


async def _require_access(update: Update, provisioner: Provisioner) -> Optional[int]:
    user_id = _user_id(update)

    if user_id is None or not provisioner.is_allowed(user_id):
        await _reply(update, "Доступ запрещен.")
        return None

    return user_id


def build_handlers(provisioner: Provisioner):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        await _reply(
            update,
            "Amnezia VPN bot\n\n"
            "/create - создать VPN-конфиг\n"
            "/status - проверить статус\n"
            "/help - список команд",
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await start(update, context)

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        exists = provisioner.client_exists(user_id)
        if exists:
            await _reply(update, "VPN-конфиг уже создан.")
        else:
            await _reply(update, "VPN-конфиг еще не создан. Используй /create.")

    async def create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        await _reply(update, "Создаю VPN-конфиг...")

        try:
            result = await asyncio.to_thread(provisioner.create_client, user_id)
        except Exception:
            logger.exception("failed to create client for telegram user %s", user_id)
            await _reply(update, "Не удалось создать VPN-конфиг. Напиши администратору.")
            return

        if result.already_exists:
            await _reply(update, "VPN-конфиг уже создан.")
            return

        await _reply(update, result.vpn_uri or "VPN-конфиг создан.")

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("status", status),
        CommandHandler("create", create),
    ]


def main() -> None:
    config = load_config_from_env()
    provisioner = Provisioner(config)

    application = Application.builder().token(config.token).build()
    for handler in build_handlers(provisioner):
        application.add_handler(handler)

    logger.info("starting telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
