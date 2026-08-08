"""Minimal Telegram Bot API client - plain HTTP, long polling.

Long polling (not a webhook) means the app needs zero inbound ports: it only
ever makes outbound HTTPS calls to api.telegram.org. See docs/ARCHITECTURE.md
section 7 for why that matters for a self-hosted deployment.

No `parse_mode` on any send/edit call, deliberately: messages here are built
from account IDs, sender email addresses, and other dynamic content that
routinely contains underscores and parentheses. Telegram's legacy Markdown
parser treats a lone `_` as an unterminated italic marker and 400s the
whole request - a real bug found by testing this end-to-end against the
live API (account_id "telegram_test" and the literal text "DRY_RUN=false"
both broke it). Plain text is worth more than bold headers here.
"""

import requests

from mailbox_agent import config
from mailbox_agent.toolkit.retry import retry_idempotent_write

_BASE = "https://api.telegram.org/bot{token}/{method}"


@retry_idempotent_write
def _call(method: str, **params):
    # getUpdates is genuinely idempotent (re-polling just re-requests, and we
    # don't advance our offset until an update is processed). sendMessage/
    # editMessageText are not quite - retrying after a lost response could
    # duplicate a Telegram message. That's an acceptable trade-off here: the
    # alternative is crashing the whole poll loop or sweep run on one
    # network blip, and a duplicate approval prompt is a minor annoyance,
    # not a correctness problem (both buttons still route to the same
    # approval_id).
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    url = _BASE.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    resp = requests.post(url, json=params, timeout=params.get("timeout", 10) + 10)

    # Telegram returns a JSON body with a human-readable "description" on
    # essentially every error, 2xx or not - read that instead of a bare
    # raise_for_status(), which only ever gives a generic "400 Bad Request"
    # and forces guessing at the real cause from HTTP status alone.
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise RuntimeError(f"Telegram API returned a non-JSON {resp.status_code} response: {resp.text[:300]}") from None

    if not data.get("ok"):
        description = data.get("description", data)
        if method == "getUpdates" and resp.status_code == 409:
            # Telegram allows exactly one active long-poll per bot token, OR
            # a webhook - not both, and not two pollers. Not transient, so
            # not retried; see docs/ARCHITECTURE.md section 7.
            raise RuntimeError(
                f"Telegram getUpdates 409: {description}. Either another process is "
                "already long-polling this bot token (mailbox-agent-telegram-bot / "
                "mailbox-agent-serve / another test run), or a webhook is registered "
                "on it (check with getWebhookInfo)."
            )
        raise RuntimeError(f"Telegram API error calling {method}: {description}")
    return data["result"]


def send_approval_request(text: str, approval_id: str) -> dict:
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve delete", "callback_data": f"approve:{approval_id}"},
                {"text": "❌ Keep / reject", "callback_data": f"reject:{approval_id}"},
            ]
        ]
    }
    return _call(
        "sendMessage",
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        reply_markup=keyboard,
    )


def get_updates(offset: int | None, timeout: int = 30) -> list[dict]:
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", **params)


def answer_callback_query(callback_query_id: str, text: str) -> None:
    _call("answerCallbackQuery", callback_query_id=callback_query_id, text=text)


def edit_message_text(chat_id: str, message_id: int, text: str) -> None:
    _call("editMessageText", chat_id=chat_id, message_id=message_id, text=text)


def notify(text: str) -> None:
    """Fire-and-forget status message, no buttons."""
    _call("sendMessage", chat_id=config.TELEGRAM_CHAT_ID, text=text)
