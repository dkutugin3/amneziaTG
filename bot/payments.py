from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class PlanOption:
    duration: str
    stars: int
    label: str


def parse_duration_label(duration: str) -> str:
    duration = duration.strip().lower()
    if duration in {"forever", "permanent", "infinite", "inf", "бессрочно"}:
        return "навсегда"

    suffix_map = {"d": "дн.", "w": "нед.", "m": "мес.", "y": "год"}
    if len(duration) >= 2 and duration[-1] in suffix_map:
        try:
            amount = int(duration[:-1])
        except ValueError:
            return duration
        return f"{amount} {suffix_map[duration[-1]]}"
    return duration


def plan_options(star_pricing: Mapping[str, int]) -> list[PlanOption]:
    return [
        PlanOption(duration=duration, stars=stars, label=parse_duration_label(duration))
        for duration, stars in star_pricing.items()
    ]


def buy_intro_text(star_pricing: Mapping[str, int]) -> str:
    lines = ["Выбери тариф подписки. Оплата в Telegram Stars.\n"]
    for duration, stars in star_pricing.items():
        lines.append(f"• {parse_duration_label(duration)} — {stars} Stars")
    lines.append("\nНажми кнопку ниже, чтобы оплатить.")
    return "\n".join(lines)


def invoice_title(duration: str) -> str:
    return f"Подписка Amnezia VPN — {parse_duration_label(duration)}"


def invoice_description(duration: str, stars: int) -> str:
    return (
        f"Доступ к Amnezia VPN на {parse_duration_label(duration)}. "
        f"Стоимость: {stars} Telegram Stars. "
        "После оплаты подписка активируется автоматически."
    )


def payment_success_text(duration: str) -> str:
    return (
        f"Оплата прошла успешно. Подписка на {parse_duration_label(duration)} продлена. "
        "Проверь статус командой /status."
    )


def payment_refunded_text() -> str:
    return "Платёж возвращён. Звёзды вернулись на твой баланс."


def terms_text(support_contact: str, terms_url: Optional[str] = None) -> str:
    lines = [
        "Условия использования",
        "",
        "1. Бот предоставляет доступ к VPN-сервису AmneziaWG на срок, указанный в тарифе.",
        "2. Оплата производится в Telegram Stars. После успешной оплаты подписка "
        "продлевается автоматически.",
        "3. Доступ может быть отозван администратором при нарушении правил сервиса.",
        "4. Возврат средств возможен через команду /paysupport в случае технических "
        "проблем со стороны сервиса.",
        "5. Подписка не является страховкой от блокировок провайдером VPN-протокола; "
        "мы прилагаем усилия для поддержания работоспособности, но не гарантируем "
        "непрерывной доступности.",
    ]
    if terms_url:
        lines.extend(["", f"Полные условия: {terms_url}"])
    lines.extend(["", f"Поддержка: {support_contact}"])
    return "\n".join(lines)


def support_text(support_contact: str) -> str:
    return (
        "Поддержка бота\n\n"
        f"По вопросам оплаты и работы VPN пишите: {support_contact}\n\n"
        "Telegram support и @botsupport не смогут помочь с покупками, "
        "сделанными в этом боте."
    )


def paysupport_text(support_contact: str) -> str:
    return (
        "Поддержка по платежам\n\n"
        f"Если возникла проблема с оплатой или нужно вернуть средства — "
        f"напиши {support_contact} с указанием Telegram ID и описанием проблемы.\n\n"
        "Мы обработаем обращение и вернём Stars при подтверждённой технической проблеме."
    )