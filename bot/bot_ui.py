BTN_ACTIVATE = "Activate access"
BTN_STATUS = "Status"
BTN_CREATE = "Create config"
BTN_HELP = "Help"
BTN_KEY_CREATE = "Create invite"
BTN_KEYS = "Invite keys"
BTN_KEY_REVOKE = "Revoke key"
BTN_USER_REVOKE = "Revoke user"
BTN_USERS = "Users"
BTN_CANCEL = "Cancel"


def keyboard_rows(is_admin: bool, is_allowed: bool) -> list[list[str]]:
    if is_admin:
        return [
            [BTN_STATUS, BTN_CREATE],
            [BTN_KEY_CREATE, BTN_KEYS],
            [BTN_USERS],
            [BTN_KEY_REVOKE, BTN_USER_REVOKE],
            [BTN_HELP],
        ]

    if is_allowed:
        return [
            [BTN_STATUS, BTN_CREATE],
            [BTN_HELP],
        ]

    return [
        [BTN_ACTIVATE],
        [BTN_HELP],
    ]


def action_for_button(text: str) -> str:
    return {
        BTN_ACTIVATE: "redeem",
        BTN_STATUS: "status",
        BTN_CREATE: "create",
        BTN_HELP: "help",
        BTN_KEY_CREATE: "key_create",
        BTN_KEYS: "keys",
        BTN_KEY_REVOKE: "key_revoke",
        BTN_USER_REVOKE: "user_revoke",
        BTN_USERS: "users",
        BTN_CANCEL: "cancel",
    }.get(text.strip(), "")
