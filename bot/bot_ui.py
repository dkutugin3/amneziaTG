from typing import Optional


BTN_ACTIVATE = "Активировать доступ"
BTN_STATUS = "Статус"
BTN_CREATE = "Создать конфиг"
BTN_GET_CONFIG = "Получить конфиг"
BTN_REPORT = "Сообщить о проблеме"
BTN_INSTRUCTIONS = "Инструкция Amnezia"
BTN_HELP = "Помощь"
BTN_KEY_CREATE = "Создать инвайт"
BTN_KEYS = "Ключи"
BTN_KEY_REVOKE = "Отозвать ключ"
BTN_USER_EXTEND = "Продлить подписку"
BTN_USER_REVOKE = "Отозвать доступ"
BTN_USERS = "Пользователи"
BTN_BROADCAST = "Рассылка"
BTN_SEND_BROADCAST = "Отправить рассылку"
BTN_CANCEL = "Отмена"


def keyboard_rows(is_admin: bool, is_allowed: bool) -> list[list[str]]:
    if is_admin:
        return [
            [BTN_STATUS, BTN_CREATE, BTN_GET_CONFIG],
            [BTN_BROADCAST, BTN_REPORT],
            [BTN_KEY_CREATE, BTN_KEYS],
            [BTN_USERS, BTN_USER_EXTEND],
            [BTN_KEY_REVOKE, BTN_USER_REVOKE],
            [BTN_INSTRUCTIONS, BTN_HELP],
        ]

    if is_allowed:
        return [
            [BTN_STATUS, BTN_CREATE, BTN_GET_CONFIG],
            [BTN_REPORT],
            [BTN_INSTRUCTIONS],
            [BTN_HELP],
        ]

    return [
        [BTN_ACTIVATE],
        [BTN_REPORT],
        [BTN_INSTRUCTIONS],
        [BTN_HELP],
    ]


def action_for_button(text: str) -> str:
    return {
        BTN_ACTIVATE: "redeem",
        BTN_STATUS: "status",
        BTN_CREATE: "create",
        BTN_GET_CONFIG: "get_config",
        BTN_REPORT: "report",
        BTN_INSTRUCTIONS: "instructions",
        BTN_HELP: "help",
        BTN_KEY_CREATE: "key_create",
        BTN_KEYS: "keys",
        BTN_KEY_REVOKE: "key_revoke",
        BTN_USER_EXTEND: "user_extend",
        BTN_USER_REVOKE: "user_revoke",
        BTN_USERS: "users",
        BTN_BROADCAST: "broadcast",
        BTN_SEND_BROADCAST: "send_broadcast",
        BTN_CANCEL: "cancel",
    }.get(text.strip(), "")


def amnezia_instruction_text() -> str:
    return (
        "Инструкция по Amnezia VPN\n\n"
        "1. Скачай Amnezia VPN из App Store, Google Play или с официального сайта.\n"
        "2. Открой Amnezia VPN.\n"
        "3. Добавь новое подключение и выбери Импорт из строки, Импорт из буфера обмена или аналогичный пункт импорта.\n"
        "4. Вставь строку конфигурации vpn:// из этого бота.\n"
        "5. Сохрани подключение и нажми подключиться."
    )


def amnezia_config_text(vpn_uri: str) -> str:
    return (
        "Это твоя строка конфигурации Amnezia VPN.\n\n"
        f"{vpn_uri}\n\n"
        "Инструкция: открой Amnezia VPN, добавь новое подключение, выбери импорт из строки/буфера обмена, "
        "вставь эту строку vpn://, затем сохрани и подключайся."
    )


def broadcast_preview_text(message: str, recipient_count: int) -> str:
    return (
        "Предпросмотр рассылки\n\n"
        f"Получателей: {recipient_count}\n\n"
        f"{message}\n\n"
        "Нажми «Отправить рассылку» для отправки или «Отмена» для отказа."
    )


def broadcast_message_text(message: str) -> str:
    return f"Объявление «Ковчег»\n\n{message}"


def invite_deep_link(bot_username: str, key: str) -> str:
    username = bot_username.strip().lstrip("@")
    return f"https://t.me/{username}?start={key.strip()}"


def invite_created_text(
    label: str,
    key: str,
    subscription_text: str,
    bot_username: Optional[str] = None,
) -> str:
    lines = [
        f"Инвайт создан для {label}:",
        "",
        key,
        "",
        f"Подписка: {subscription_text}",
    ]
    if bot_username:
        lines.extend([
            "",
            "Ссылка-инвайт:",
            invite_deep_link(bot_username, key),
        ])
    lines.extend([
        "",
        "Отправь ключ или ссылку-инвайт пользователю. "
        "Ключ привяжется к первому Telegram ID, который его активирует.",
    ])
    return "\n".join(lines)


def report_confirmation_text() -> str:
    return "Твоё обращение отправлено администраторам. Они его проверят."


def report_admin_text(actor: str, message: str, access_status: str) -> str:
    return (
        "Обращение пользователя\n\n"
        f"пользователь: {actor}\n"
        f"доступ: {access_status}\n\n"
        f"{message}"
    )
