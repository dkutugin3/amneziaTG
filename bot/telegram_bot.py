#!/usr/bin/env python3
import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from bot.access_store import AccessStore
    from bot.bot_core import Provisioner, load_config_from_env
    from bot.bot_ui import (
        BTN_CANCEL,
        BTN_SEND_BROADCAST,
        action_for_button,
        amnezia_config_text,
        amnezia_instruction_text,
        broadcast_message_text,
        broadcast_preview_text,
        invite_created_text,
        keyboard_rows,
        report_admin_text,
        report_confirmation_text,
    )
except ImportError:
    from access_store import AccessStore
    from bot_core import Provisioner, load_config_from_env
    from bot_ui import (
        BTN_CANCEL,
        BTN_SEND_BROADCAST,
        action_for_button,
        amnezia_config_text,
        amnezia_instruction_text,
        broadcast_message_text,
        broadcast_preview_text,
        invite_created_text,
        keyboard_rows,
        report_admin_text,
        report_confirmation_text,
    )


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


def _broadcast_confirm_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_SEND_BROADCAST], [BTN_CANCEL]], resize_keyboard=True)


def _actor(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown user"

    username = f"@{user.username}" if user.username else "no username"
    name = user.full_name or "no name"
    return f"{name} ({username}, id={user.id})"


def _format_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _format_subscription_status(status: str, expires_at: Optional[int]) -> str:
    if status == "revoked":
        return "revoked"
    if status == "expired":
        if expires_at is None:
            return "expired"
        return f"expired on {_format_date(expires_at)}"
    if expires_at is None:
        return "forever"
    return f"active until {_format_date(expires_at)}"


def _duration_help_text() -> str:
    return "Отправь срок подписки: 7d, 30d, 90d, 365d или forever."


async def _notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    provisioner: Provisioner,
    text: str,
) -> None:
    await _notify_admins_with_bot(context.bot, provisioner, text)


async def _notify_admins_with_bot(bot, provisioner: Provisioner, text: str) -> None:
    for admin_id in sorted(provisioner.config.admin_ids):
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("failed to notify admin %s", admin_id)


async def _send_subscription_notifications(
    bot,
    provisioner: Provisioner,
    access_store: AccessStore,
) -> None:
    for notification in access_store.subscription_notifications_due():
        date = _format_date(notification.expires_at)
        sent_any = False
        user_text = (
            "Твоя подписка Amnezia VPN скоро закончится.\n"
            f"Осталось дней: {notification.days_left}\n"
            f"Дата окончания: {date}"
        )
        try:
            await bot.send_message(chat_id=notification.tg_id, text=user_text)
            sent_any = True
        except Exception:
            logger.exception(
                "failed to send subscription notification to user %s",
                notification.tg_id,
            )

        admin_text = (
            "Subscription ending soon\n"
            f"user_tg_id: {notification.tg_id}\n"
            f"label: {notification.label}\n"
            f"days_left: {notification.days_left}\n"
            f"expires: {date}"
        )
        for admin_id in sorted(provisioner.config.admin_ids):
            try:
                await bot.send_message(chat_id=admin_id, text=admin_text)
                sent_any = True
            except Exception:
                logger.exception("failed to notify admin %s", admin_id)

        if sent_any:
            access_store.mark_subscription_notified(
                notification.tg_id,
                days_left=notification.days_left,
            )


async def _subscription_notifier_loop(
    application: Application,
    provisioner: Provisioner,
    access_store: AccessStore,
) -> None:
    while True:
        await _send_subscription_notifications(application.bot, provisioner, access_store)
        await asyncio.sleep(provisioner.config.subscription_check_interval_seconds)


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
        "Report issue - сообщить админам о проблеме\n"
        "Amnezia instructions - инструкция по установке конфига\n"
        "Status - проверить статус\n"
        "Help - показать это меню"
    )


def admin_help_text() -> str:
    return (
        "Amnezia VPN bot admin\n\n"
        "Create invite - создать invite key со сроком подписки\n"
        "Invite keys - список ключей\n"
        "Extend user - продлить подписку пользователя\n"
        "Revoke key - отозвать ключ\n"
        "Revoke user - отозвать доступ пользователя\n"
        "Users - список пользователей\n"
        "Broadcast - массовая рассылка активным пользователям\n"
        "Report issue - сообщить админам о проблеме\n"
        "Create config - создать VPN-конфиг для себя\n"
        "Amnezia instructions - инструкция по установке конфига\n"
        "Status - проверить свой статус"
    )


def build_handlers(provisioner: Provisioner, access_store: AccessStore):
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if context.args:
            await _redeem_key(update, context, context.args[0])
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
            "expired": "Срок действия этого ключа истек.",
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
        subscription = access_store.get_subscription(user_id)
        if subscription is None and provisioner.is_admin(user_id):
            lines.append("subscription: admin")
        elif subscription is not None:
            lines.append(
                "subscription: "
                + _format_subscription_status(subscription.status, subscription.expires_at)
            )
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

        if result.vpn_uri:
            await _reply(
                update,
                amnezia_config_text(result.vpn_uri),
                _menu_markup(provisioner, user_id),
            )
        else:
            await _reply(update, "VPN-конфиг Amnezia создан.", _menu_markup(provisioner, user_id))
        await _notify_admins(
            context,
            provisioner,
            f"Config created\nuser: {_actor(update)}\nclient: {result.client_name}",
        )

    async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        await _reply(update, amnezia_instruction_text(), _menu_markup(provisioner, user_id))

    async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        if context.args:
            await _send_report(update, context, " ".join(context.args), user_id)
            return

        context.user_data["pending_action"] = "report_issue"
        await _reply(
            update,
            "Опиши проблему одним сообщением. Например: не подключается VPN, не открывается конфиг, не работает ключ.",
            _cancel_markup(),
        )

    async def _send_report(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        user_id: int,
    ) -> None:
        clean_message = message.strip()
        if not clean_message:
            context.user_data["pending_action"] = "report_issue"
            await _reply(update, "Сообщение не должно быть пустым. Опиши проблему.", _cancel_markup())
            return

        if provisioner.is_admin(user_id):
            access_status = "admin"
        elif provisioner.is_allowed(user_id):
            access_status = "active"
        else:
            access_status = "not active"

        await _notify_admins(
            context,
            provisioner,
            report_admin_text(
                actor=_actor(update),
                message=clean_message,
                access_status=access_status,
            ),
        )
        await _reply(update, report_confirmation_text(), _menu_markup(provisioner, user_id))

    async def key_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if len(context.args) >= 2:
            label = " ".join(context.args[:-1]).strip()
            duration = context.args[-1]
            await _create_invite(update, context, label, duration, admin_id)
            return

        if len(context.args) == 1:
            context.user_data["pending_action"] = "key_create_duration"
            context.user_data["pending_invite_label"] = context.args[0]
            await _reply(update, _duration_help_text(), _cancel_markup())
            return

        context.user_data["pending_action"] = "key_create_label"
        await _reply(update, "Отправь имя/label для invite key.", _cancel_markup())
        return

    async def _ask_invite_duration(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        label: str,
    ) -> None:
        context.user_data["pending_action"] = "key_create_duration"
        context.user_data["pending_invite_label"] = label.strip() or "friend"
        await _reply(update, _duration_help_text(), _cancel_markup())

    async def _create_invite(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        label: str,
        duration: str,
        admin_id: int,
    ) -> None:
        try:
            invite = access_store.create_invite(
                label,
                created_by_tg_id=admin_id,
                duration=duration,
            )
        except ValueError as exc:
            context.user_data["pending_action"] = "key_create_duration"
            context.user_data["pending_invite_label"] = label.strip() or "friend"
            await _reply(update, f"{exc}\n{_duration_help_text()}", _cancel_markup())
            return

        subscription_text = _format_subscription_status("active", invite.expires_at)
        await _reply(
            update,
            invite_created_text(
                label=invite.label,
                key=invite.key,
                subscription_text=subscription_text,
                bot_username=provisioner.config.bot_username,
            ),
            _menu_markup(provisioner, admin_id),
        )
        await _notify_admins(
            context,
            provisioner,
            "Invite key created\n"
            f"admin: {_actor(update)}\n"
            f"label: {invite.label}\n"
            f"subscription: {subscription_text}\n"
            f"key: {invite.key}",
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
            state = _format_subscription_status(item.status, item.expires_at)
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
            state = _format_subscription_status(item.status, item.expires_at)
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

    async def user_extend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if len(context.args) < 2:
            context.user_data["pending_action"] = "user_extend"
            await _reply(
                update,
                "Отправь Telegram ID и срок: 123456789 30d или 123456789 forever.",
                _cancel_markup(),
            )
            return

        await _extend_user(update, context, " ".join(context.args), admin_id)

    async def _extend_user(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        raw_value: str,
        admin_id: int,
    ) -> None:
        parts = raw_value.split()
        if len(parts) != 2:
            await _reply(
                update,
                "Формат: <telegram_id> <duration>, например 123456789 30d или 123456789 forever.",
                _menu_markup(provisioner, admin_id),
            )
            return

        raw_tg_id, duration = parts
        try:
            tg_id = int(raw_tg_id)
        except ValueError:
            await _reply(update, "tg_id должен быть числом.", _menu_markup(provisioner, admin_id))
            return

        try:
            updated = access_store.extend_user(tg_id, duration)
        except ValueError as exc:
            await _reply(update, f"{exc}\n{_duration_help_text()}", _menu_markup(provisioner, admin_id))
            return

        if not updated:
            await _reply(update, "Пользователь не найден или доступ отозван.", _menu_markup(provisioner, admin_id))
            result = "not found"
            subscription_text = "unknown"
        else:
            subscription = access_store.get_subscription(tg_id)
            subscription_text = (
                _format_subscription_status(subscription.status, subscription.expires_at)
                if subscription is not None
                else "unknown"
            )
            await _reply(
                update,
                f"Подписка обновлена: {subscription_text}.",
                _menu_markup(provisioner, admin_id),
            )
            result = "extended"

        await _notify_admins(
            context,
            provisioner,
            "User subscription extend: "
            f"{result}\nadmin: {_actor(update)}\n"
            f"target_tg_id: {raw_tg_id}\nsubscription: {subscription_text}",
        )

    async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if context.args:
            await _preview_broadcast(update, context, " ".join(context.args), admin_id)
            return

        context.user_data["pending_action"] = "broadcast_message"
        await _reply(
            update,
            "Отправь текст массовой рассылки для всех активных пользователей.",
            _cancel_markup(),
        )

    async def _preview_broadcast(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        admin_id: int,
    ) -> None:
        clean_message = message.strip()
        if not clean_message:
            context.user_data["pending_action"] = "broadcast_message"
            await _reply(update, "Текст рассылки не должен быть пустым.", _cancel_markup())
            return

        recipients = access_store.list_broadcast_recipients()
        context.user_data["pending_broadcast_message"] = clean_message
        context.user_data["pending_action"] = "broadcast_confirm"
        await _reply(
            update,
            broadcast_preview_text(clean_message, recipient_count=len(recipients)),
            _broadcast_confirm_markup(),
        )

    async def _send_broadcast(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        admin_id: int,
    ) -> None:
        message = context.user_data.pop("pending_broadcast_message", "").strip()
        if not message:
            await _reply(update, "Нет подготовленной рассылки.", _menu_markup(provisioner, admin_id))
            return

        recipients = access_store.list_broadcast_recipients()
        delivered = 0
        failed = 0
        text = broadcast_message_text(message)
        for recipient in recipients:
            try:
                await context.bot.send_message(chat_id=recipient.tg_id, text=text)
                delivered += 1
            except Exception:
                failed += 1
                logger.exception("failed to send broadcast to user %s", recipient.tg_id)

        summary = (
            "Broadcast sent\n"
            f"admin: {_actor(update)}\n"
            f"recipients: {len(recipients)}\n"
            f"delivered: {delivered}\n"
            f"failed: {failed}"
        )
        await _reply(update, summary, _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, summary)

    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None or update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()
        action = action_for_button(text)

        if action == "cancel":
            context.user_data.pop("pending_action", None)
            context.user_data.pop("pending_invite_label", None)
            context.user_data.pop("pending_broadcast_message", None)
            await _reply(update, "Ок, отменено.", _menu_markup(provisioner, user_id))
            return
        if action == "send_broadcast":
            context.user_data.pop("pending_action", None)
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _send_broadcast(update, context, admin_id)
            return

        pending_action = context.user_data.pop("pending_action", None)
        if pending_action == "redeem":
            await _redeem_key(update, context, text)
            return
        if pending_action == "key_create_label":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _ask_invite_duration(update, context, text)
            return
        if pending_action == "key_create_duration":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                label = context.user_data.pop("pending_invite_label", "friend")
                await _create_invite(update, context, label, text, admin_id)
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
        if pending_action == "user_extend":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _extend_user(update, context, text, admin_id)
            return
        if pending_action == "broadcast_message":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _preview_broadcast(update, context, text, admin_id)
            return
        if pending_action == "broadcast_confirm":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "broadcast_confirm"
                await _reply(
                    update,
                    "Нажми Send broadcast для отправки или Cancel для отмены.",
                    _broadcast_confirm_markup(),
                )
            return
        if pending_action == "report_issue":
            await _send_report(update, context, text, user_id)
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
        if action == "instructions":
            await instructions(update, context)
            return
        if action == "report":
            await report(update, context)
            return
        if action == "help":
            await help_command(update, context)
            return
        if action == "key_create":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "key_create_label"
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
        if action == "user_extend":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "user_extend"
                await _reply(
                    update,
                    "Отправь Telegram ID и срок: 123456789 30d или 123456789 forever.",
                    _cancel_markup(),
                )
            return
        if action == "broadcast":
            await broadcast(update, context)
            return

        await _reply(update, "Выбери действие кнопкой ниже.", _menu_markup(provisioner, user_id))

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("redeem", redeem),
        CommandHandler("status", status),
        CommandHandler("create", create),
        CommandHandler("instructions", instructions),
        CommandHandler("report", report),
        CommandHandler("key_create", key_create),
        CommandHandler("keys", keys),
        CommandHandler("key_revoke", key_revoke),
        CommandHandler("users", users),
        CommandHandler("user_revoke", user_revoke),
        CommandHandler("user_extend", user_extend),
        CommandHandler("broadcast", broadcast),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
    ]


def main() -> None:
    config = load_config_from_env()
    access_store = AccessStore(config.db_path)
    provisioner = Provisioner(config, access_store=access_store)

    async def post_init(application: Application) -> None:
        application.create_task(
            _subscription_notifier_loop(application, provisioner, access_store)
        )

    application = Application.builder().token(config.token).post_init(post_init).build()
    for handler in build_handlers(provisioner, access_store):
        application.add_handler(handler)

    logger.info("starting telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
