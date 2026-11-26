"""Telegram Bot API (standard library). Only the owner's chat is obeyed; every sent message is also saved
to the state bucket under feed/<day>/ for the app's Feed tab.

Until switch-over this is the second bot (/upx/telegram-bot-token-v2); UPX_TELEGRAM_TOKEN_PARAM changes it.
"""
import json
import os
from datetime import datetime, timedelta, timezone

from core import http, ssm, storage

IST = timezone(timedelta(hours=5, minutes=30))
TOKEN_PARAM = os.environ.get("UPX_TELEGRAM_TOKEN_PARAM", "/upx/telegram-bot-token-v2")
CHAT_PARAM = "/upx/telegram-chat-id"


def _chat_id():
    return ssm.get(CHAT_PARAM)


def _api(method, **params):
    token = ssm.get(TOKEN_PARAM)
    body = http.request("POST", f"https://api.telegram.org/bot{token}/{method}",
                        headers={"Content-Type": "application/json"}, data=json.dumps(params).encode(),
                        timeout=40, log_url=f"telegram {method}")  # never log the token
    reply = json.loads(body)
    if not reply.get("ok"):
        raise RuntimeError(f"telegram {method}: {reply.get('description')}")
    return reply["result"]


def _markup(buttons):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}


def send(text, buttons=None, reply_to=None, now_ist=None):
    params = {"chat_id": _chat_id(), "text": text[:4000], "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = _markup(buttons)
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to}
    mid = _api("sendMessage", **params)["message_id"]
    now = now_ist or datetime.now(IST).isoformat(timespec="seconds")
    storage.put_json(f"feed/{now[:10]}/{now[11:19].replace(':', '')}-{mid}.json",
                     {"ts": now, "id": mid, "text": text, "reply_to": reply_to})
    return mid


def edit(message_id, text, buttons=None):
    params = {"chat_id": _chat_id(), "message_id": message_id, "text": text[:4000]}
    if buttons is not None:
        params["reply_markup"] = _markup(buttons)
    _api("editMessageText", **params)


def answer_button(callback_id, text=""):
    _api("answerCallbackQuery", callback_query_id=callback_id, text=text)


def poll(offset, wait=25):
    """New updates from the owner's chat only: commands, button taps, reactions. Returns (updates, next offset)."""
    raw = _api("getUpdates", offset=offset, timeout=wait,
               allowed_updates=["message", "callback_query", "message_reaction"])
    owner = str(_chat_id())
    out = []
    for u in raw:
        offset = max(offset, u["update_id"] + 1)
        if "message" in u and str(u["message"]["chat"]["id"]) == owner and u["message"].get("text"):
            out.append({"kind": "command", "text": u["message"]["text"].strip()})
        elif "callback_query" in u and str(u["callback_query"]["message"]["chat"]["id"]) == owner:
            out.append({"kind": "button", "id": u["callback_query"]["id"], "data": u["callback_query"]["data"]})
        elif "message_reaction" in u and str(u["message_reaction"]["chat"]["id"]) == owner:
            emoji = [r.get("emoji") for r in u["message_reaction"].get("new_reaction", []) if r.get("type") == "emoji"]
            out.append({"kind": "reaction", "message_id": u["message_reaction"]["message_id"],
                        "emoji": emoji[0] if emoji else None})
    return out, offset
