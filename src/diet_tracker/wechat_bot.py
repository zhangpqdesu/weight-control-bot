from __future__ import annotations

import time
from pathlib import Path

from .config import Settings, load_settings
from .models import PersonKey
from .service import DietTrackerService


HELP = """减肥记录机器人
发餐食文字或图片即可记录。
命令：
/今天 查看自己的今日统计
/help 查看帮助
"""


def resolve_person(settings: Settings, sender_name: str) -> PersonKey | None:
    for key, person in settings.people.items():
        if person.wechat_name and person.wechat_name == sender_name:
            return key  # type: ignore[return-value]
    return None


def run() -> None:
    try:
        from wxauto import WeChat
    except ImportError as exc:
        raise RuntimeError("Install wxauto first: pip install wxauto") from exc

    settings = load_settings()
    if not settings.wechat_group_name:
        raise RuntimeError("Set WECHAT_GROUP_NAME in .env")

    service = DietTrackerService(settings)
    wx = WeChat()
    wx.AddListenChat(who=settings.wechat_group_name, savepic=True)
    print(f"Listening to WeChat group: {settings.wechat_group_name}")

    while True:
        messages = wx.GetListenMessage()
        for chat, msg_list in messages.items():
            for msg in msg_list:
                sender = getattr(msg, "sender", "") or getattr(msg, "Sender", "")
                content = getattr(msg, "content", "") or getattr(msg, "Content", "")
                msg_type = getattr(msg, "type", "") or getattr(msg, "Type", "")
                person_key = resolve_person(settings, sender)
                if not person_key:
                    continue

                reply = handle_message(
                    service=service,
                    person_key=person_key,
                    content=content,
                    msg_type=str(msg_type),
                )
                if reply:
                    chat.SendMsg(reply)
        time.sleep(2)


def handle_message(
    service: DietTrackerService,
    person_key: PersonKey,
    content: str,
    msg_type: str,
) -> str | None:
    text = (content or "").strip()
    if text in {"/help", "help", "帮助"}:
        return HELP
    if text in {"/今天", "今天", "/today"}:
        return service.today_reply(person_key)

    image_path = _extract_image_path(text, msg_type)
    if not text and not image_path:
        return None

    entry = service.add_food(
        person_key=person_key,
        text=text if not image_path else None,
        image_path=image_path,
    )
    return service.entry_reply(entry)


def _extract_image_path(content: str, msg_type: str) -> Path | None:
    if "image" not in msg_type.lower() and "图片" not in msg_type:
        return None
    candidate = Path(content.strip().strip('"'))
    return candidate if candidate.exists() else None


if __name__ == "__main__":
    run()

