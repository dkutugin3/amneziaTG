#!/usr/bin/env python3
import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

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
    from bot.payments import (
        buy_intro_text,
        invoice_description,
        invoice_title,
        parse_duration_label,
        payment_refunded_text,
        payment_success_text,
        paysupport_text,
        plan_options,
        support_text,
        terms_text,
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
    from payments import (
        buy_intro_text,
        invoice_description,
        invoice_title,
        parse_duration_label,
        payment_refunded_text,
        payment_success_text,
        paysupport_text,
        plan_options,
        support_text,
        terms_text,
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
        input_field_placeholder="Выбери действие",
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
        return "отозван"
    if status == "expired":
        if expires_at is None:
            return "истёк"
        return f"истёк {_format_date(expires_at)}"
    if expires_at is None:
        return "бессрочно"
    return f"активна до {_format_date(expires_at)}"


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
        await _reply(update, "Доступ не активирован. Нажми кнопку «Активировать доступ».")
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
        "Бот Amnezia VPN\n\n"
        "Активировать доступ — активировать инвайт-ключ\n"
        "Создать конфиг — создать VPN-конфиг\n"
        "Получить конфиг — получить существующий VPN-конфиг\n"
        "Купить подписку — продлить подписку за Telegram Stars\n"
        "Сообщить о проблеме — сообщить админам о проблеме\n"
        "Инструкция Amnezia — инструкция по установке конфига\n"
        "Статус — проверить статус\n"
        "Помощь — показать это меню\n\n"
        "/terms — условия использования\n"
        "/support — контакты поддержки\n"
        "/paysupport — поддержка по платежам"
    )


def admin_help_text() -> str:
    return (
        "Бот Amnezia VPN — администрирование\n\n"
        "Создать инвайт — создать инвайт-ключ со сроком подписки\n"
        "Ключи — список ключей\n"
        "Продлить подписку — продлить подписку пользователя\n"
        "Отозвать ключ — отозвать ключ\n"
        "Отозвать доступ — отозвать доступ пользователя\n"
        "Пользователи — список пользователей\n"
        "Рассылка — массовая рассылка активным пользователям\n"
        "Возвраты — список платежей в Stars и возвраты\n"
        "Сообщить о проблеме — сообщить админам о проблеме\n"
        "Создать конфиг — создать VPN-конфиг для себя\n"
        "Получить конфиг — получить существующий VPN-конфиг\n"
        "Купить подписку — продлить свою подписку\n"
        "Инструкция Amnezia — инструкция по установке конфига\n"
        "Статус — проверить свой статус\n\n"
        "/terms — условия использования\n"
        "/support — контакты поддержки\n"
        "/paysupport — поддержка по платежам"
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
                "Бот Amnezia VPN\n\nНажми «Активировать доступ» и отправь инвайт-ключ.",
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
            await _reply(update, "Отправь инвайт-ключ одним сообщением.", _cancel_markup())
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
            "expired": "Срок действия этого ключа истёк.",
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
            f"Активация инвайт-ключа: {result.status}\nпользователь: {_actor(update)}",
        )

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        exists = provisioner.client_exists(user_id)
        client = access_store.get_client(user_id)
        lines = [
            "доступ: активен",
            f"клиент: {client.client_name if client else 'tg_' + str(user_id)}",
            f"конфиг: {'создан' if exists else 'не создан'}",
        ]
        subscription = access_store.get_subscription(user_id)
        if subscription is None and provisioner.is_admin(user_id):
            lines.append("подписка: админ")
        elif subscription is not None:
            lines.append(
                "подписка: "
                + _format_subscription_status(subscription.status, subscription.expires_at)
            )
        await _reply(update, "\n".join(lines), _menu_markup(provisioner, user_id))
        await _notify_admins(
            context,
            provisioner,
            f"Проверка статуса\nпользователь: {_actor(update)}\nконфиг: {'создан' if exists else 'не создан'}",
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
                f"Ошибка создания конфига\nпользователь: {_actor(update)}",
            )
            return

        if result.already_exists:
            await _reply(update, "VPN-конфиг уже создан. Нажми «Получить конфиг».", _menu_markup(provisioner, user_id))
            await _notify_admins(
                context,
                provisioner,
                f"Создание конфига пропущено: уже существует\nпользователь: {_actor(update)}\nклиент: {result.client_name}",
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
            f"Конфиг создан\nпользователь: {_actor(update)}\nклиент: {result.client_name}",
        )

    async def get_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = await _require_access(update, provisioner)
        if user_id is None:
            return

        if not provisioner.client_exists(user_id):
            await _reply(update, "VPN-конфиг ещё не создан. Нажми «Создать конфиг».", _menu_markup(provisioner, user_id))
            return

        await _reply(update, "Получаю VPN-конфиг...", _menu_markup(provisioner, user_id))

        try:
            vpn_uri = await asyncio.to_thread(provisioner.get_client_config, user_id)
        except Exception:
            logger.exception("failed to get client config for telegram user %s", user_id)
            await _reply(update, "Не удалось получить VPN-конфиг. Напиши администратору.")
            await _notify_admins(
                context,
                provisioner,
                f"Ошибка получения конфига\nпользователь: {_actor(update)}",
            )
            return

        await _reply(
            update,
            amnezia_config_text(vpn_uri),
            _menu_markup(provisioner, user_id),
        )
        await _notify_admins(
            context,
            provisioner,
            f"Конфиг получен\nпользователь: {_actor(update)}",
        )

    async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        await _reply(update, amnezia_instruction_text(), _menu_markup(provisioner, user_id))

    async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return

        pricing = provisioner.config.star_pricing
        if not pricing:
            await _reply(update, "Оплата временно недоступна. Напиши администратору.", _menu_markup(provisioner, user_id))
            return

        options = plan_options(pricing)
        buttons: list[list[InlineKeyboardButton]] = []
        for option in options:
            buttons.append([
                InlineKeyboardButton(
                    text=f"{option.label} — {option.stars} Stars",
                    callback_data=f"buy:{option.duration}:{option.stars}",
                )
            ])
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            buy_intro_text(pricing),
            reply_markup=markup,
        )

    async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None or query.data is None:
            return

        parts = query.data.split(":")
        if len(parts) != 3 or parts[0] != "buy":
            return

        duration = parts[1]
        try:
            stars = int(parts[2])
        except ValueError:
            return

        if duration not in provisioner.config.star_pricing:
            await query.answer("Тариф не найден. Обнови меню.")
            return

        if provisioner.config.star_pricing[duration] != stars:
            await query.answer("Цена изменилась. Обнови меню.")
            return

        await query.answer()

        if query.from_user is None:
            return
        tg_id = query.from_user.id

        try:
            await context.bot.send_invoice(
                chat_id=update.effective_chat.id if update.effective_chat else tg_id,
                title=invoice_title(duration),
                description=invoice_description(duration, stars),
                payload=f"vpn_sub:{duration}:{tg_id}",
                provider_token="",
                currency="XTR",
                prices=[{"label": parse_duration_label(duration), "amount": stars}],
                start_parameter="buy",
            )
        except Exception:
            logger.exception("failed to send invoice to user %s", tg_id)
            await query.message.reply_text(
                "Не удалось выставить счёт. Напиши администратору.",
                reply_markup=_menu_markup(provisioner, tg_id),
            )

    async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.pre_checkout_query
        if query is None:
            return

        if query.invoice_payload is None:
            await query.answer(ok=False, error_message="Некорректный платёж.")
            return

        parts = query.invoice_payload.split(":")
        if len(parts) < 2 or parts[0] != "vpn_sub":
            await query.answer(ok=False, error_message="Некорректный платёж.")
            return

        duration = parts[1]
        if duration not in provisioner.config.star_pricing:
            await query.answer(ok=False, error_message="Тариф не найден.")
            return

        if query.total_amount != provisioner.config.star_pricing[duration]:
            await query.answer(ok=False, error_message="Сумма не совпадает с тарифом.")
            return

        await query.answer(ok=True)

    async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or message.successful_payment is None:
            return

        payment = message.successful_payment
        if payment.invoice_payload is None:
            logger.warning("successful_payment without invoice_payload from user %s", _actor(update))
            return

        parts = payment.invoice_payload.split(":")
        if len(parts) < 2 or parts[0] != "vpn_sub":
            logger.warning("unexpected invoice_payload: %s", payment.invoice_payload)
            return

        duration = parts[1]
        if duration not in provisioner.config.star_pricing:
            logger.warning("unknown duration in successful_payment: %s", duration)
            return

        user_id = _user_id(update)
        if user_id is None:
            return

        charge_id = payment.telegram_payment_charge_id or ""
        stars = payment.total_amount or 0

        try:
            access_store.record_star_payment(
                tg_id=user_id,
                telegram_payment_charge_id=charge_id,
                duration=duration,
                stars=stars,
            )
        except Exception:
            logger.exception("failed to record star payment for user %s", user_id)

        if not access_store.is_user_active(user_id):
            invite_label = f"stars_{user_id}"
            try:
                access_store.create_invite(
                    label=invite_label,
                    created_by_tg_id=user_id,
                    duration=duration,
                )
            except Exception:
                logger.exception("failed to create invite for stars buyer %s", user_id)
                await _reply(
                    update,
                    "Оплата получена, но не удалось активировать доступ. Напиши /paysupport.",
                    _menu_markup(provisioner, user_id),
                )
                return

            invites = access_store.list_invites()
            for item in invites:
                if item.label == invite_label and item.tg_id == 0:
                    access_store.redeem_invite(
                        _invite_key_for_label(invites, invite_label),
                        tg_id=user_id,
                    )
                    break
            else:
                logger.warning("no invite created for stars buyer %s", user_id)
                await _reply(
                    update,
                    "Оплата получена, но не удалось привязать ключ. Напиши /paysupport.",
                    _menu_markup(provisioner, user_id),
                )
                return

        try:
            updated = access_store.extend_user(user_id, duration)
        except ValueError:
            updated = False

        if not updated:
            logger.warning("extend_user failed for stars buyer %s, duration=%s", user_id, duration)
            await _reply(
                update,
                "Оплата получена, но продлить подписку не удалось. Напиши /paysupport.",
                _menu_markup(provisioner, user_id),
            )
            return

        await _reply(
            update,
            payment_success_text(duration),
            _menu_markup(provisioner, user_id),
        )
        await _notify_admins(
            context,
            provisioner,
            "Stars payment\n"
            f"user: {_actor(update)}\n"
            f"duration: {duration}\n"
            f"stars: {stars}\n"
            f"charge_id: {charge_id}",
        )

    def _invite_key_for_label(invites, label):
        for item in invites:
            if item.label == label:
                return getattr(item, "key", label)
        return label

    async def terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return
        await _reply(
            update,
            terms_text(provisioner.config.support_contact, provisioner.config.terms_url),
            _menu_markup(provisioner, user_id),
        )

    async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return
        await _reply(
            update,
            support_text(provisioner.config.support_contact),
            _menu_markup(provisioner, user_id),
        )

    async def paysupport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = _user_id(update)
        if user_id is None:
            return
        await _reply(
            update,
            paysupport_text(provisioner.config.support_contact),
            _menu_markup(provisioner, user_id),
        )

    async def refunds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if context.args:
            await _refund_star_payment(update, context, context.args[0], admin_id)
            return

        payments = access_store.list_star_payments(limit=30)
        if not payments:
            await _reply(update, "Платежей в Stars пока нет.", _menu_markup(provisioner, admin_id))
            return

        lines = []
        for payment in payments[:30]:
            state = "возвращён" if payment.refunded else "активен"
            lines.append(
                f"{payment.tg_id}: {payment.duration}, {payment.stars} XTR, {state}\n"
                f"  charge_id: {payment.telegram_payment_charge_id}"
            )

        await _reply(update, "\n".join(lines), _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, f"Список платежей Stars\nадмин: {_actor(update)}")

    async def _refund_star_payment(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        charge_id: str,
        admin_id: int,
    ) -> None:
        record = access_store.get_star_payment_by_charge_id(charge_id)
        if record is None:
            await _reply(update, "Платёж не найден.", _menu_markup(provisioner, admin_id))
            return

        if record.refunded:
            await _reply(update, "Платёж уже возвращён.", _menu_markup(provisioner, admin_id))
            return

        try:
            await context.bot.refund_star_payment(
                user_id=record.tg_id,
                telegram_payment_charge_id=record.telegram_payment_charge_id,
            )
        except Exception:
            logger.exception("failed to refund star payment %s", charge_id)
            await _reply(
                update,
                "Не удалось вернуть платёж. Проверь логи.",
                _menu_markup(provisioner, admin_id),
            )
            return

        access_store.mark_star_payment_refunded(charge_id)
        await _reply(update, payment_refunded_text(), _menu_markup(provisioner, admin_id))
        await _notify_admins(
            context,
            provisioner,
            f"Refund Stars payment\nadmin: {_actor(update)}\n"
            f"tg_id: {record.tg_id}\nstars: {record.stars}\ncharge_id: {charge_id}",
        )

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
            access_status = "админ"
        elif provisioner.is_allowed(user_id):
            access_status = "активен"
        else:
            access_status = "не активен"

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
        await _reply(update, "Отправь имя/метку для инвайт-ключа.", _cancel_markup())
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
            "Инвайт-ключ создан\n"
            f"админ: {_actor(update)}\n"
            f"метка: {invite.label}\n"
            f"подписка: {subscription_text}\n"
            f"ключ: {invite.key}",
        )

    async def keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        invites = access_store.list_invites()
        if not invites:
            await _reply(update, "Инвайт-ключей пока нет.", _menu_markup(provisioner, admin_id))
            return

        lines = []
        for item in invites[:30]:
            owner = str(item.tg_id) if item.tg_id else "не использован"
            state = _format_subscription_status(item.status, item.expires_at)
            lines.append(f"{item.label}: {owner}, {state}")

        await _reply(update, "\n".join(lines), _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, f"Список инвайт-ключей\nадмин: {_actor(update)}")

    async def key_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            context.user_data["pending_action"] = "key_revoke"
            await _reply(update, "Отправь инвайт-ключ, который нужно отозвать.", _cancel_markup())
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
            result = "отозван"
        else:
            await _reply(update, "Ключ не найден.", _menu_markup(provisioner, admin_id))
            result = "не найден"
        await _notify_admins(context, provisioner, f"Отзыв инвайт-ключа: {result}\nадмин: {_actor(update)}")

    async def users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        users_list = access_store.list_users()
        if not users_list:
            await _reply(update, "Активированных пользователей пока нет.", _menu_markup(provisioner, admin_id))
            return

        lines = []
        for item in users_list[:30]:
            state = _format_subscription_status(item.status, item.expires_at)
            client = item.client_name or f"tg_{item.tg_id}"
            lines.append(f"{item.tg_id}: {item.label}, {state}, {client}")

        await _reply(update, "\n".join(lines), _menu_markup(provisioner, admin_id))
        await _notify_admins(context, provisioner, f"Список пользователей\nадмин: {_actor(update)}")

    async def user_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        admin_id = await _require_admin(update, provisioner)
        if admin_id is None:
            return

        if not context.args:
            context.user_data["pending_action"] = "user_revoke"
            await _reply(update, "Отправь Telegram ID пользователя для отзыва доступа.", _cancel_markup())
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
            await _reply(update, "Telegram ID должен быть числом.", _menu_markup(provisioner, admin_id))
            return

        if access_store.revoke_user(tg_id):
            await _reply(update, "Доступ пользователя отозван.", _menu_markup(provisioner, admin_id))
            result = "отозван"
        else:
            await _reply(update, "Активный пользователь не найден.", _menu_markup(provisioner, admin_id))
            result = "не найден"
        await _notify_admins(
            context,
            provisioner,
            f"Отзыв пользователя: {result}\nадмин: {_actor(update)}\ntg_id: {raw_tg_id}",
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
                "Формат: <telegram_id> <срок>, например 123456789 30d или 123456789 forever.",
                _menu_markup(provisioner, admin_id),
            )
            return

        raw_tg_id, duration = parts
        try:
            tg_id = int(raw_tg_id)
        except ValueError:
            await _reply(update, "Telegram ID должен быть числом.", _menu_markup(provisioner, admin_id))
            return

        try:
            updated = access_store.extend_user(tg_id, duration)
        except ValueError as exc:
            await _reply(update, f"{exc}\n{_duration_help_text()}", _menu_markup(provisioner, admin_id))
            return

        if not updated:
            await _reply(update, "Пользователь не найден или доступ отозван.", _menu_markup(provisioner, admin_id))
            result = "не найден"
            subscription_text = "неизвестно"
        else:
            subscription = access_store.get_subscription(tg_id)
            subscription_text = (
                _format_subscription_status(subscription.status, subscription.expires_at)
                if subscription is not None
                else "неизвестно"
            )
            await _reply(
                update,
                f"Подписка обновлена: {subscription_text}.",
                _menu_markup(provisioner, admin_id),
            )
            result = "продлена"

        await _notify_admins(
            context,
            provisioner,
            "Продление подписки пользователя: "
            f"{result}\nадмин: {_actor(update)}\n"
            f"tg_id: {raw_tg_id}\nподписка: {subscription_text}",
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
            "Рассылка отправлена\n"
            f"админ: {_actor(update)}\n"
            f"получателей: {len(recipients)}\n"
            f"доставлено: {delivered}\n"
            f"ошибок: {failed}"
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
                    "Нажми «Отправить рассылку» для отправки или «Отмена» для отказа.",
                    _broadcast_confirm_markup(),
                )
            return
        if pending_action == "report_issue":
            await _send_report(update, context, text, user_id)
            return
        if pending_action == "refunds":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                await _refund_star_payment(update, context, text, admin_id)
            return

        if action == "redeem":
            context.user_data["pending_action"] = "redeem"
            await _reply(update, "Отправь инвайт-ключ одним сообщением.", _cancel_markup())
            return
        if action == "status":
            await status(update, context)
            return
        if action == "create":
            await create(update, context)
            return
        if action == "get_config":
            await get_config(update, context)
            return
        if action == "instructions":
            await instructions(update, context)
            return
        if action == "buy":
            await buy(update, context)
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
                await _reply(update, "Отправь имя/метку для инвайт-ключа.", _cancel_markup())
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
                await _reply(update, "Отправь инвайт-ключ, который нужно отозвать.", _cancel_markup())
            return
        if action == "user_revoke":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "user_revoke"
                await _reply(update, "Отправь Telegram ID пользователя для отзыва доступа.", _cancel_markup())
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
        if action == "refunds":
            admin_id = await _require_admin(update, provisioner)
            if admin_id is not None:
                context.user_data["pending_action"] = "refunds"
                await _reply(
                    update,
                    "Отправь telegram_payment_charge_id для возврата или пустое сообщение для списка.",
                    _cancel_markup(),
                )
            return

        await _reply(update, "Выбери действие кнопкой ниже.", _menu_markup(provisioner, user_id))

    return [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("redeem", redeem),
        CommandHandler("status", status),
        CommandHandler("create", create),
        CommandHandler("get_config", get_config),
        CommandHandler("instructions", instructions),
        CommandHandler("buy", buy),
        CommandHandler("terms", terms),
        CommandHandler("support", support),
        CommandHandler("paysupport", paysupport),
        CommandHandler("report", report),
        CommandHandler("key_create", key_create),
        CommandHandler("keys", keys),
        CommandHandler("key_revoke", key_revoke),
        CommandHandler("users", users),
        CommandHandler("user_revoke", user_revoke),
        CommandHandler("user_extend", user_extend),
        CommandHandler("broadcast", broadcast),
        CommandHandler("refunds", refunds),
        PreCheckoutQueryHandler(pre_checkout),
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment),
        CallbackQueryHandler(buy_callback, pattern=r"^buy:"),
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
