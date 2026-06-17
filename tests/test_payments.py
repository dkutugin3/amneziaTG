import unittest

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


class PaymentsTextTest(unittest.TestCase):
    def test_parse_duration_label_translates_units(self):
        self.assertEqual(parse_duration_label("7d"), "7 дн.")
        self.assertEqual(parse_duration_label("2w"), "2 нед.")
        self.assertEqual(parse_duration_label("1m"), "1 мес.")
        self.assertEqual(parse_duration_label("1y"), "1 год")
        self.assertEqual(parse_duration_label("forever"), "навсегда")
        self.assertEqual(parse_duration_label("30d"), "30 дн.")

    def test_plan_options_returns_sorted_by_input_order(self):
        pricing = {"7d": 25, "30d": 75, "365d": 600}
        options = plan_options(pricing)

        self.assertEqual(len(options), 3)
        self.assertEqual(options[0].duration, "7d")
        self.assertEqual(options[0].stars, 25)
        self.assertEqual(options[0].label, "7 дн.")
        self.assertEqual(options[2].duration, "365d")
        self.assertEqual(options[2].label, "365 дн.")

    def test_buy_intro_text_lists_all_plans_with_stars(self):
        text = buy_intro_text({"7d": 25, "30d": 75})

        self.assertIn("7 дн. — 25 Stars", text)
        self.assertIn("30 дн. — 75 Stars", text)
        self.assertIn("Telegram Stars", text)

    def test_invoice_title_includes_duration_label(self):
        self.assertIn("7 дн.", invoice_title("7d"))
        self.assertIn("навсегда", invoice_title("forever"))

    def test_invoice_description_includes_duration_and_stars(self):
        text = invoice_description("30d", 75)

        self.assertIn("30 дн.", text)
        self.assertIn("75", text)

    def test_payment_success_text_mentions_duration(self):
        self.assertIn("7 дн.", payment_success_text("7d"))

    def test_payment_refunded_text_is_short(self):
        self.assertIn("возвращён", payment_refunded_text().lower())

    def test_terms_text_includes_support_and_url(self):
        text = terms_text("@vpn_support", "https://example.com/terms")

        self.assertIn("@vpn_support", text)
        self.assertIn("https://example.com/terms", text)

    def test_terms_text_without_url_omits_link(self):
        text = terms_text("@vpn_support")

        self.assertIn("@vpn_support", text)
        self.assertNotIn("Полные условия", text)

    def test_support_text_mentions_contact_and_telegram_disclaimer(self):
        text = support_text("@vpn_support")

        self.assertIn("@vpn_support", text)
        self.assertIn("не смогут помочь", text)

    def test_paysupport_text_mentions_contact(self):
        self.assertIn("@vpn_support", paysupport_text("@vpn_support"))


if __name__ == "__main__":
    unittest.main()