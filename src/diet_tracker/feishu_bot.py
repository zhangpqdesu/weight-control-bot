from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .feishu_im import FeishuImClient
from .models import PersonKey
from .service import DietTrackerService


HELP = """减肥记录机器人
发文字或图片给机器人即可记录。
命令：
/今天 查看自己的今日统计
/help 查看帮助
"""


def resolve_person(settings: Settings, open_id: str) -> PersonKey | None:
    for key, person in settings.people.items():
        if person.feishu_open_id and person.feishu_open_id == open_id:
            return key  # type: ignore[return-value]
    return None


class FeishuDietBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service = DietTrackerService(settings)
        self.im = FeishuImClient(settings)
        self.media_dir = Path("data/feishu_media")

    def handle_message_event(self, event: Any) -> None:
        event_dict = _to_dict(event)
        message = _dig(event_dict, "event", "message") or _dig(event_dict, "message") or {}
        sender = _dig(event_dict, "event", "sender", "sender_id") or _dig(event_dict, "sender", "sender_id") or {}

        message_id = str(message.get("message_id") or "")
        message_type = str(message.get("message_type") or "")
        content = _parse_content(message.get("content"))
        open_id = str(sender.get("open_id") or "")

        if not message_id or not open_id:
            return

        person_key = resolve_person(self.settings, open_id)
        if not person_key:
            self.im.reply_text(message_id, "我还不认识这个飞书用户，请先把 open_id 配到 .env。")
            return

        try:
            reply = self._handle_content(person_key, message_type, content, message_id)
        except Exception as exc:
            reply = f"记录失败：{exc}"
        if reply:
            self.im.reply_text(message_id, reply)

    def _handle_content(
        self,
        person_key: PersonKey,
        message_type: str,
        content: dict[str, Any],
        message_id: str,
    ) -> str | None:
        if message_type == "text":
            text = str(content.get("text") or "").strip()
            if text in {"/help", "help", "帮助"}:
                return HELP
            if text in {"/今天", "今天", "/today"}:
                return self.service.today_reply(person_key)
            entry = self.service.add_food(person_key=person_key, text=text, image_path=None)
            return self.service.entry_reply(entry)

        if message_type == "image":
            image_key = str(content.get("image_key") or "")
            if not image_key:
                return "这张图片没有 image_key，暂时无法下载。"
            image_path = self.im.download_message_image(message_id, image_key, self.media_dir)
            entry = self.service.add_food(person_key=person_key, text=None, image_path=image_path)
            return self.service.entry_reply(entry)

        return None


def run() -> None:
    try:
        import lark_oapi as lark
    except ImportError as exc:
        raise RuntimeError("Install lark-oapi first: pip install lark-oapi") from exc

    settings = load_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("Set FEISHU_APP_ID and FEISHU_APP_SECRET in .env")

    bot = FeishuDietBot(settings)

    event_handler = (
        lark.EventDispatcherHandler.builder(
            settings.feishu_verification_token,
            settings.feishu_encrypt_key,
        )
        .register_p2_im_message_receive_v1(lambda event: bot.handle_message_event(event))
        .build()
    )

    client = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    print("Feishu diet bot is running with websocket event subscription.")
    client.start()


def _parse_content(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    return json.loads(str(raw))


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        import lark_oapi as lark

        return json.loads(lark.JSON.marshal(value))
    except Exception:
        return json.loads(json.dumps(value, default=lambda obj: getattr(obj, "__dict__", str(obj))))


def _dig(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


if __name__ == "__main__":
    run()

