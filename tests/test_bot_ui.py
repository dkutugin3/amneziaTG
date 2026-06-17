import unittest

from bot.bot_ui import (
    BTN_ACTIVATE,
    BTN_BROADCAST,
    BTN_CANCEL,
    BTN_CREATE,
    BTN_HELP,
    BTN_INSTRUCTIONS,
    BTN_KEY_CREATE,
    BTN_KEY_REVOKE,
    BTN_KEYS,
    BTN_REPORT,
    BTN_SEND_BROADCAST,
    BTN_STATUS,
    BTN_USER_EXTEND,
    BTN_USER_REVOKE,
    BTN_USERS,
    action_for_button,
    amnezia_config_text,
    amnezia_instruction_text,
    broadcast_message_text,
    broadcast_preview_text,
    keyboard_rows,
    report_admin_text,
    report_confirmation_text,
)


class BotUiTest(unittest.TestCase):
    def test_inactive_user_keyboard_only_offers_activation_and_help(self):
        self.assertEqual(
            keyboard_rows(is_admin=False, is_allowed=False),
            [[BTN_ACTIVATE], [BTN_REPORT], [BTN_INSTRUCTIONS], [BTN_HELP]],
        )

    def test_allowed_user_keyboard_offers_status_create_instructions_and_help(self):
        self.assertEqual(
            keyboard_rows(is_admin=False, is_allowed=True),
            [[BTN_STATUS, BTN_CREATE], [BTN_REPORT], [BTN_INSTRUCTIONS], [BTN_HELP]],
        )

    def test_admin_keyboard_contains_admin_actions(self):
        rows = keyboard_rows(is_admin=True, is_allowed=True)
        flat = [button for row in rows for button in row]

        self.assertIn(BTN_KEY_CREATE, flat)
        self.assertIn(BTN_KEYS, flat)
        self.assertIn(BTN_KEY_REVOKE, flat)
        self.assertIn(BTN_USER_EXTEND, flat)
        self.assertIn(BTN_USER_REVOKE, flat)
        self.assertIn(BTN_USERS, flat)
        self.assertIn(BTN_INSTRUCTIONS, flat)
        self.assertIn(BTN_BROADCAST, flat)
        self.assertIn(BTN_REPORT, flat)

    def test_action_for_button_maps_input_buttons(self):
        self.assertEqual(action_for_button(BTN_ACTIVATE), "redeem")
        self.assertEqual(action_for_button(BTN_KEY_CREATE), "key_create")
        self.assertEqual(action_for_button(BTN_KEY_REVOKE), "key_revoke")
        self.assertEqual(action_for_button(BTN_USER_EXTEND), "user_extend")
        self.assertEqual(action_for_button(BTN_USER_REVOKE), "user_revoke")
        self.assertEqual(action_for_button(BTN_CANCEL), "cancel")
        self.assertEqual(action_for_button(BTN_INSTRUCTIONS), "instructions")
        self.assertEqual(action_for_button(BTN_SEND_BROADCAST), "send_broadcast")
        self.assertEqual(action_for_button(BTN_REPORT), "report")

    def test_action_for_button_maps_direct_buttons(self):
        self.assertEqual(action_for_button(BTN_STATUS), "status")
        self.assertEqual(action_for_button(BTN_CREATE), "create")
        self.assertEqual(action_for_button(BTN_KEYS), "keys")
        self.assertEqual(action_for_button(BTN_USERS), "users")
        self.assertEqual(action_for_button(BTN_HELP), "help")
        self.assertEqual(action_for_button(BTN_BROADCAST), "broadcast")

    def test_amnezia_config_text_identifies_config_and_includes_vpn_uri(self):
        text = amnezia_config_text("vpn://abc")

        self.assertIn("Amnezia VPN", text)
        self.assertIn("vpn://abc", text)
        self.assertIn("Instructions", text)

    def test_amnezia_instruction_text_explains_import_flow(self):
        text = amnezia_instruction_text()

        self.assertIn("Download Amnezia VPN", text)
        self.assertIn("Import", text)
        self.assertIn("vpn://", text)

    def test_broadcast_text_helpers_format_preview_and_message(self):
        preview = broadcast_preview_text("Update tonight", recipient_count=3)
        message = broadcast_message_text("Update tonight")

        self.assertIn("Broadcast preview", preview)
        self.assertIn("Recipients: 3", preview)
        self.assertIn("Update tonight", preview)
        self.assertIn("Amnezia VPN announcement", message)
        self.assertIn("Update tonight", message)

    def test_report_text_helpers_format_confirmation_and_admin_notification(self):
        confirmation = report_confirmation_text()
        admin_text = report_admin_text(
            actor="Alice (@alice, id=42)",
            message="VPN does not connect",
            access_status="active",
        )

        self.assertIn("sent to admins", confirmation)
        self.assertIn("User report", admin_text)
        self.assertIn("Alice", admin_text)
        self.assertIn("active", admin_text)
        self.assertIn("VPN does not connect", admin_text)


if __name__ == "__main__":
    unittest.main()
