#!/usr/bin/env python3
import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    from bot.access_store import AccessStore
    from bot.bot_core import Provisioner, load_config_from_env
except ImportError:
    from access_store import AccessStore
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
        await _reply(update, "Доступ не активирован. Отправь /redeem <ключ>.")
        return None

    return user_id


async def _require_admin(update: Update, provisioner: Provisioner) -> Optional[int]:
    user_id = _user_id(update)

    if user_id is None or not provisioner.is_admin(user_id):
        await _reply(update, "Команда доступна только администратору.")
        return None

    return user_id


def user_help_text() -> str:
    return (
        "Amnezia VPN bot\n\n"
        "/redeem <ключ> - активировать доступ\n"
        "/create - создать VPN-конфиг\n"
        "/status - проверить статус\n"
        "/help - список команд"
    )


def admin_help_text() -> str:
    return (
        "Amnezia VPN bot admin\n\n"
        "/key_create <name> - создать invite key\n"
        "/keys - список ключей\n"
        "/key_revoke <key> - отозвать ключ\n"
        "/user_revoke <tg_id> - отозвать доступ пользователя\n"
        "/users - список пользователей\n"
        "/create - создать VPN-конфиг для себя\n"
        "/status - проверить свой статус"
    )


def build_handlers(provisioner: Provisioner, access_store: AccessStore):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if provisioner.is_admin(user_id):
            await _reply(update, admin_help_text())
        elif provisioner.is_allowed(user_id):
            await _reply(update, user_help_text())
        else:
            await _reply(update, "Amnezia VPN bot\n\nОтправь /redeem <ключ>, чтобы активировать доступ.")

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await start(update, context)

    async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if not context.args:
            await _reply(update, "Использование: /redeem <ключ>")
            return

        result = access_store.redeem_invite(context.args[0], user_id)
        messages = {
            "redeemed": "Доступ активирован. Теперь можно использовать /status и /create.",
            "already_redeemed": "Этот ключ уже активирован для твоего Telegram ID.",
            "already_bound": "Этот ключ уже привязан к другому Telegram ID.",
            "revoked": "Этот ключ отозван.",
            "invalid": "Ключ не найден.",
            "user_already_active": "У тебя уже есть активный доступ.",
        }
        await _reply(update, messages.get(result.status, "Не удалось активировать ключ."))

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        exists = provisioner.client_exists(user_id)
        client = access_store.get_client(user_id)
        lines = [
            "access: active",
            f"client: {client.client_name if client else 'tg_' + str(user_id)}",
            f"config: {'created' if exists else 'not created'}",
        ]
        await _reply(update, "\n".join(lines))

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

    async def key_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        label = " ".join(context.args).strip()
        if not label:
            await _reply(update, "Использование: /key_create <name>")
            return

        invite = access_store.create_invite(label, created_by_tg_id=admin_id)
        await _reply(
            update,
            f"Invite key created for {invite.label}:\n\n{invite.key}\n\n"
            "Send this key to the user. It will bind to the first Telegram ID that redeems it.",
        )

    async def keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        invites = access_store.list_invites()
        if not invites:
            await _reply(update, "No invite keys yet.")
            return

        lines = []
        for item in invites[:30]:
            owner = str(item.tg_id) if item.tg_id else "unused"
            state = "revoked" if item.revoked else "active"
            lines.append(f"{item.label}: {owner}, {state}")

        await _reply(update, "\n".join(lines))

    async def key_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            await _reply(update, "Использование: /key_revoke <ключ>")
            return

        if access_store.revoke_invite(context.args[0]):
            await _reply(update, "Ключ отозван.")
        else:
            await _reply(update, "Ключ не найден.")

    async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        users_list = access_store.list_users()
        if not users_list:
            await _reply(update, "No activated users yet.")
            return

        lines = []
        for item in users_list[:30]:
            state = "revoked" if item.revoked else "active"
            client = item.client_name or f"tg_{item.tg_id}"
            lines.append(f"{item.tg_id}: {item.label}, {state}, {client}")

        await _reply(update, "\n".join(lines))

    async def user_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            await _reply(update, "Использование: /user_revoke <tg_id>")
            return

        try:
            tg_id = int(context.args[0])
        except ValueError:
            await _reply(update, "tg_id должен быть числом.")
            return

        if access_store.revoke_user(tg_id):
            await _reply(update, "Доступ пользователя отозван.")
        else:
            await _reply(update, "Активный пользователь не найден.")

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("redeem", redeem),
        CommandHandler("status", status),
        CommandHandler("create", create),
        CommandHandler("key_create", key_create),
        CommandHandler("keys", keys),
        CommandHandler("key_revoke", key_revoke),
        CommandHandler("users", users),
        CommandHandler("user_revoke", user_revoke),
    ]


def main() -> None:
    config = load_config_from_env()
    access_store = AccessStore(config.db_path)
    provisioner = Provisioner(config, access_store=access_store)

    application = Application.builder().token(config.token).build()
    for handler in build_handlers(provisioner, access_store):
        application.add_handler(handler)

    logger.info("starting telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
