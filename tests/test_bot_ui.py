import unittest

from bot.bot_ui import (
    BTN_ACTIVATE,
    BTN_CANCEL,
    BTN_CREATE,
    BTN_HELP,
    BTN_KEY_CREATE,
    BTN_KEY_REVOKE,
    BTN_KEYS,
    BTN_STATUS,
    BTN_USER_REVOKE,
    BTN_USERS,
    action_for_button,
    keyboard_rows,
)


class BotUiTest(unittest.TestCase):
    def test_inactive_user_keyboard_only_offers_activation_and_help(self):
        self.assertEqual(keyboard_rows(is_admin=False, is_allowed=False), [[BTN_ACTIVATE], [BTN_HELP]])

    def test_allowed_user_keyboard_offers_status_create_and_help(self):
        self.assertEqual(
            keyboard_rows(is_admin=False, is_allowed=True),
            [[BTN_STATUS, BTN_CREATE], [BTN_HELP]],
        )

    def test_admin_keyboard_contains_admin_actions(self):
        rows = keyboard_rows(is_admin=True, is_allowed=True)
        flat = [button for row in rows for button in row]

        self.assertIn(BTN_KEY_CREATE, flat)
        self.assertIn(BTN_KEYS, flat)
        self.assertIn(BTN_KEY_REVOKE, flat)
        self.assertIn(BTN_USER_REVOKE, flat)
        self.assertIn(BTN_USERS, flat)

    def test_action_for_button_maps_input_buttons(self):
        self.assertEqual(action_for_button(BTN_ACTIVATE), "redeem")
        self.assertEqual(action_for_button(BTN_KEY_CREATE), "key_create")
        self.assertEqual(action_for_button(BTN_KEY_REVOKE), "key_revoke")
        self.assertEqual(action_for_button(BTN_USER_REVOKE), "user_revoke")
        self.assertEqual(action_for_button(BTN_CANCEL), "cancel")

    def test_action_for_button_maps_direct_buttons(self):
        self.assertEqual(action_for_button(BTN_STATUS), "status")
        self.assertEqual(action_for_button(BTN_CREATE), "create")
        self.assertEqual(action_for_button(BTN_KEYS), "keys")
        self.assertEqual(action_for_button(BTN_USERS), "users")
        self.assertEqual(action_for_button(BTN_HELP), "help")


if __name__ == "__main__":
    unittest.main()
