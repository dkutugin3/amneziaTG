BTN_ACTIVATE = "Activate access"
BTN_STATUS = "Status"
BTN_CREATE = "Create config"
BTN_REPORT = "Report issue"
BTN_INSTRUCTIONS = "Amnezia instructions"
BTN_HELP = "Help"
BTN_KEY_CREATE = "Create invite"
BTN_KEYS = "Invite keys"
BTN_KEY_REVOKE = "Revoke key"
BTN_USER_EXTEND = "Extend user"
BTN_USER_REVOKE = "Revoke user"
BTN_USERS = "Users"
BTN_BROADCAST = "Broadcast"
BTN_SEND_BROADCAST = "Send broadcast"
BTN_CANCEL = "Cancel"


def keyboard_rows(is_admin: bool, is_allowed: bool) -> list[list[str]]:
    if is_admin:
        return [
            [BTN_STATUS, BTN_CREATE],
            [BTN_KEY_CREATE, BTN_KEYS],
            [BTN_USERS],
            [BTN_USER_EXTEND],
            [BTN_KEY_REVOKE, BTN_USER_REVOKE],
            [BTN_BROADCAST],
            [BTN_REPORT],
            [BTN_INSTRUCTIONS],
            [BTN_HELP],
        ]

    if is_allowed:
        return [
            [BTN_STATUS, BTN_CREATE],
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
        "Instructions for Amnezia VPN\n\n"
        "1. Download Amnezia VPN from the App Store, Google Play, or the official desktop app.\n"
        "2. Open Amnezia VPN.\n"
        "3. Add a new connection and choose Import from string, Import from clipboard, or a similar import option.\n"
        "4. Paste the vpn:// configuration string from this bot.\n"
        "5. Save the connection and connect."
    )


def amnezia_config_text(vpn_uri: str) -> str:
    return (
        "This is your Amnezia VPN configuration string.\n\n"
        f"{vpn_uri}\n\n"
        "Instructions: open Amnezia VPN, add a new connection, choose import from string/clipboard, "
        "paste this vpn:// string, then save and connect."
    )


def broadcast_preview_text(message: str, recipient_count: int) -> str:
    return (
        "Broadcast preview\n\n"
        f"Recipients: {recipient_count}\n\n"
        f"{message}\n\n"
        "Press Send broadcast to deliver this message, or Cancel to discard it."
    )


def broadcast_message_text(message: str) -> str:
    return f"Amnezia VPN announcement\n\n{message}"


def report_confirmation_text() -> str:
    return "Your report was sent to admins. They will check it."


def report_admin_text(actor: str, message: str, access_status: str) -> str:
    return (
        "User report\n\n"
        f"user: {actor}\n"
        f"access: {access_status}\n\n"
        f"{message}"
    )
