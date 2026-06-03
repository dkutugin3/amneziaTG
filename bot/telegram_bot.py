#!/usr/bin/env python3
import asyncio
import logging
from typing import Optional

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from bot.access_store import AccessStore
    from bot.bot_core import Provisioner, load_config_from_env
    from bot.bot_ui import (
        BTN_CANCEL,
        action_for_button,
        keyboard_rows,
    )
except ImportError:
    from access_store import AccessStore
    from bot_core import Provisioner, load_config_from_env
    from bot_ui import BTN_CANCEL, action_for_button, keyboard_rows


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


async def _reply(update: Update, text: str, reply_markup=None) -> None:
    if update.message is not None:
        await update.message.reply_text(text, reply_markup=reply_markup)


def _menu_markup(provisioner: Provisioner, user_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard_rows(
            is_admin=provisioner.is_admin(user_id),
            is_allowed=provisioner.is_allowed(user_id),
        ),
        resize_keyboard=True,
        input_field_placeholder="Choose action",
    )


def _cancel_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


def _actor(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown user"

    username = f"@{user.username}" if user.username else "no username"
    name = user.full_name or "no name"
    return f"{name} ({username}, id={user.id})"


async def _notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    provisioner: Provisioner,
    text: str,
) -> None:
    for admin_id in sorted(provisioner.config.admin_ids):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("failed to notify admin %s", admin_id)


async def _require_access(update: Update, provisioner: Provisioner) -> Optional[int]:
    user_id = _user_id(update)

    if user_id is None or not provisioner.is_allowed(user_id):
        await _reply(update, "Доступ не активирован. Нажми кнопку Activate access.")
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
        "Activate access - активировать invite key\n"
        "Create config - создать VPN-конфиг\n"
        "Status - проверить статус\n"
        "Help - показать это меню"
    )


def admin_help_text() -> str:
    return (
        "Amnezia VPN bot admin\n\n"
        "Create invite - создать invite key\n"
        "Invite keys - список ключей\n"
        "Revoke key - отозвать ключ\n"
        "Revoke user - отозвать доступ пользователя\n"
        "Users - список пользователей\n"
        "Create config - создать VPN-конфиг для себя\n"
        "Status - проверить свой статус"
    )


def build_handlers(provisioner: Provisioner, access_store: AccessStore):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if provisioner.is_admin(user_id):
            await _reply(update, admin_help_text(), _menu_markup(provisioner, user_id))
        elif provisioner.is_allowed(user_id):
            await _reply(update, user_help_text(), _menu_markup(provisioner, user_id))
        else:
            await _reply(
                update,
                "Amnezia VPN bot\n\nНажми Activate access и отправь invite key.",
                _menu_markup(provisioner, user_id),
            )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await start(update, context)

    async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if not context.args:
            context.user_data["pending_action"] = "redeem"
            await _reply(update, "Отправь invite key одним сообщением.", _cancel_markup())
            return

        await _redeem_key(update, context, context.args[0])

    async def _redeem_key(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        key: str,
    ) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        result = access_store.redeem_invite(key, user_id)
        messages = {
            "redeemed": "Доступ активирован. Теперь можно использовать /status и /create.",
            "already_redeemed": "Этот ключ уже активирован для твоего Telegram ID.",
            "already_bound": "Этот ключ уже привязан к другому Telegram ID.",
            "revoked": "Этот ключ отозван.",
            "invalid": "Ключ не найден.",
            "user_already_active": "У тебя уже есть активный доступ.",
        }
        await _reply(
            update,
            messages.get(result.status, "Не удалось активировать ключ."),
            _menu_markup(provisioner, user_id),
        )
        await _notify_admins(
            context,
            provisioner,
            f"Access key redeem: {result.status}\nuser: {_actor(update)}",
        )

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
        await _reply(update, "\n".join(lines), _menu_markup(provisioner, user_id))
        await _notify_admins(
            context,
            provisioner,
            f"Status checked\nuser: {_actor(update)}\nconfig: {'created' if exists else 'not created'}",
        )

    async def create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        await _reply(update, "Создаю VPN-конфиг...", _menu_markup(provisioner, user_id))

        try:
            result = await asyncio.to_thread(provisioner.create_client, user_id)
        except Exception:
            logger.exception("failed to create client for telegram user %s", user_id)
            await _reply(update, "Не удалось создать VPN-конфиг. Напиши администратору.")
            await _notify_admins(
                context,
                provisioner,
                f"Config creation failed\nuser: {_actor(update)}",
            )
            return

        if result.already_exists:
            await _reply(update, "VPN-конфиг уже создан.", _menu_markup(provisioner, user_id))
            await _notify_admins(
                context,
                provisioner,
                f"Config creation skipped: already exists\nuser: {_actor(update)}\nclient: {result.client_name}",
            )
            return

        await _reply(update, result.vpn_uri or "VPN-конфиг создан.", _menu_markup(provisioner, user_id))
        await _notify_admins(
            context,
            provisioner,
            f"Config created\nuser: {_actor(update)}\nclient: {result.client_name}",
        )

    async def key_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        label = " ".join(context.args).strip()
        if not label:
            context.user_data["pending_action"] = "key_create"
            await _reply(update, "Отправь имя/label для invite key.", _cancel_markup())
            return

        await _create_invite(update, context, label, admin_id)

    async def _create_invite(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        label: str,
        admin_id: int,
    ) -> None:
        invite = access_store.create_invite(label, created_by_tg_id=admin_id)
        await _reply(
            update,
            f"Invite key created for {invite.label}:\n\n{invite.key}\n\n"
            "Send this key to the user. It will bind to the first Telegram ID that redeems it.",
            _menu_markup(provisioner, admin_id),
        )
        await _notify_admins(
            context,
            provisioner,
            f"Invite key created\nadmin: {_actor(update)}\nlabel: {invite.label}\nkey: {invite.key}",
        )

    async def keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        invites = access_store.list_invites()
        if not invites:
            await _reply(update, "No invite keys yet.", _menu_markup(provisioner, admin_id))
            return

        lines = []
        for item in invites[:30]:
            owner = str(item.tg_id) if item.tg_id else "unused"
            state = "revoked" if item.revoked else "active"
            lines.append(f"{item.label}: {owner}, {state}")

        await _reply(update, "\n".join(lines), _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, f"Invite keys listed\nadmin: {_actor(update)}")

    async def key_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            context.user_data["pending_action"] = "key_revoke"
            await _reply(update, "Отправь invite key, который нужно отозвать.", _cancel_markup())
            return

        await _revoke_key(update, context, context.args[0], admin_id)

    async def _revoke_key(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        key: str,
        admin_id: int,
    ) -> None:
        if access_store.revoke_invite(key):
            await _reply(update, "Ключ отозван.", _menu_markup(provisioner, admin_id))
            result = "revoked"
        else:
            await _reply(update, "Ключ не найден.", _menu_markup(provisioner, admin_id))
            result = "not found"
        await _notify_admins(context, provisioner, f"Invite key revoke: {result}\nadmin: {_actor(update)}")

    async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        users_list = access_store.list_users()
        if not users_list:
            await _reply(update, "No activated users yet.", _menu_markup(provisioner, admin_id))
            return

        lines = []
        for item in users_list[:30]:
            state = "revoked" if item.revoked else "active"
            client = item.client_name or f"tg_{item.tg_id}"
            lines.append(f"{item.tg_id}: {item.label}, {state}, {client}")

        await _reply(update, "\n".join(lines), _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, f"Users listed\nadmin: {_actor(update)}")

    async def user_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            context.user_data["pending_action"] = "user_revoke"
            await _reply(update, "Отправь Telegram ID пользователя для отзыва.", _cancel_markup())
            return

        await _revoke_user(update, context, context.args[0], admin_id)

    async def _revoke_user(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        raw_tg_id: str,
        admin_id: int,
    ) -> None:
        try:
            tg_id = int(raw_tg_id)
        except ValueError:
            await _reply(update, "tg_id должен быть числом.", _menu_markup(provisioner, admin_id))
            return

        if access_store.revoke_user(tg_id):
            await _reply(update, "Доступ пользователя отозван.", _menu_markup(provisioner, admin_id))
            result = "revoked"
        else:
            await _reply(update, "Активный пользователь не найден.", _menu_markup(provisioner, admin_id))
            result = "not found"
        await _notify_admins(
            context,
            provisioner,
            f"User revoke: {result}\nadmin: {_actor(update)}\ntarget_tg_id: {raw_tg_id}",
        )

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None or update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()
        action = action_for_button(text)

        if action == "cancel":
            context.user_data.pop("pending_action", None)
            await _reply(update, "Ок, отменено.", _menu_markup(provisioner, user_id))
            return

        pending_action = context.user_data.pop("pending_action", None)
        if pending_action == "redeem":
            await _redeem_key(update, context, text)
            return
        if pending_action == "key_create":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _create_invite(update, context, text, admin_id)
            return
        if pending_action == "key_revoke":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _revoke_key(update, context, text, admin_id)
            return
        if pending_action == "user_revoke":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _revoke_user(update, context, text, admin_id)
            return

        if action == "redeem":
            context.user_data["pending_action"] = "redeem"
            await _reply(update, "Отправь invite key одним сообщением.", _cancel_markup())
            return
        if action == "status":
            await status(update, context)
            return
        if action == "create":
            await create(update, context)
            return
        if action == "help":
            await help_command(update, context)
            return
        if action == "key_create":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "key_create"
                await _reply(update, "Отправь имя/label для invite key.", _cancel_markup())
            return
        if action == "keys":
            await keys(update, context)
            return
        if action == "users":
            await users(update, context)
            return
        if action == "key_revoke":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "key_revoke"
                await _reply(update, "Отправь invite key, который нужно отозвать.", _cancel_markup())
            return
        if action == "user_revoke":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "user_revoke"
                await _reply(update, "Отправь Telegram ID пользователя для отзыва.", _cancel_markup())
            return

        await _reply(update, "Выбери действие кнопкой ниже.", _menu_markup(provisioner, user_id))

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
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
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
