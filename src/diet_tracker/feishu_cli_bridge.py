from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .feishu_fields import food_entry_to_feishu_fields
from .models import FoodEntry
from .models import PersonKey
from .service import DietTrackerService


HELP = """减肥记录机器人
发文字或图片给机器人即可记录。
命令：
/今天 查看自己的今日统计
/我是小张 或 我是小张 绑定为小张
/我是小韩 或 我是小韩 绑定为小韩
/help 查看帮助
"""

IMAGE_KEY_PATTERN = re.compile(r"img_[A-Za-z0-9_-]+")


class FeishuCliBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service = DietTrackerService(settings)
        self.lark_cli = _split_command(os.getenv("LARK_CLI_CMD", "lark-cli"))
        self.sync_mode = os.getenv("FEISHU_SYNC_MODE", "api").lower()
        self.media_dir = Path("data/feishu_cli_media")

    def run_stdin_loop(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                self.handle_event(event)
            except Exception as exc:
                print(f"failed to handle event: {exc}", file=sys.stderr, flush=True)

    def handle_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("message_id") or event.get("id") or "")
        message_type = str(event.get("message_type") or "")
        sender_id = str(event.get("sender_id") or "")
        chat_id = str(event.get("chat_id") or "")
        chat_type = str(event.get("chat_type") or "")
        content = str(event.get("content") or "").strip()

        if not message_id or not sender_id:
            return

        mentioned_bot = self._has_leading_mention(content)
        clean_content = self._strip_leading_mention(content)

        bind_key = self._match_bind_command(message_type, clean_content)
        if bind_key:
            person = self.settings.people[bind_key]
            self.service.db.bind_feishu_user(sender_id, bind_key, person.display_name)
            self.reply_text(
                message_id,
                f"已绑定：{person.display_name}\n以后你的饮食会记录到 {person.display_name} 的每日统计里。",
            )
            return

        if chat_type == "group" and not self._should_handle_group_message(
            message_type=message_type,
            content=clean_content,
            mentioned_bot=mentioned_bot,
            bind_key=bind_key,
        ):
            return

        person_key = self._resolve_person(sender_id)
        if not person_key:
            self.reply_text(
                message_id,
                "我还不认识你。\n"
                "如果你是小张，请发：我是小张\n"
                "如果你是小韩，请发：我是小韩",
            )
            return

        try:
            reply = self._handle_message(
                person_key=person_key,
                sender_id=sender_id,
                chat_id=chat_id,
                chat_type=chat_type,
                message_id=message_id,
                message_type=message_type,
                content=clean_content,
            )
        except Exception as exc:
            reply = f"记录失败：{exc}"
        if reply:
            self.reply_text(message_id, reply)

    def _handle_message(
        self,
        person_key: PersonKey,
        sender_id: str,
        chat_id: str,
        chat_type: str,
        message_id: str,
        message_type: str,
        content: str,
    ) -> str | None:
        if message_type == "text":
            if content in {"/help", "help", "帮助"}:
                return HELP
            if content in {"/今天", "今天", "/today"}:
                return self.service.today_reply(person_key)
            if self._looks_like_image_reference(content):
                target_person_key = self._mentioned_person_key(content) or person_key
                image_path = self.service.db.latest_feishu_image(sender_id, chat_id)
                if not image_path and chat_type == "group":
                    latest = self.service.db.latest_feishu_image_in_chat(chat_id)
                    if latest:
                        image_sender_id, image_path = latest
                        target_person_key = (
                            self._mentioned_person_key(content)
                            or self._resolve_person(image_sender_id)
                            or person_key
                        )
                if not image_path:
                    return (
                        "我没拿到你前面那张图片。\n"
                        "可选办法：\n"
                        "1. 私聊我直接发图片；\n"
                        "2. 在飞书开放平台给机器人开通“获取群组中所有消息/读取群组消息”权限，重新发布；\n"
                        "3. 发图后 15 分钟内再 @ 我说“看图”。"
                    )
                entry = self.service.add_food(
                    person_key=target_person_key,
                    text=content,
                    image_path=Path(image_path),
                )
                self.sync_base_with_cli(entry)
                return self.service.entry_reply(entry)
            entry = self.service.add_food(person_key=person_key, text=content, image_path=None)
            self.sync_base_with_cli(entry)
            return self.service.entry_reply(entry)

        if message_type == "image":
            image_key = self._extract_image_key(content)
            if not image_key:
                return (
                    "收到图片，但 CLI 事件里没有 image_key。\n"
                    "请用 `lark-cli event schema im.message.receive_v1` 确认图片事件 content 格式。"
                )
            image_path = self.download_message_image(message_id, image_key)
            self.service.db.remember_feishu_image(
                open_id=sender_id,
                chat_id=chat_id,
                message_id=message_id,
                image_path=str(image_path),
            )
            if chat_type == "group":
                return None
            entry = self.service.add_food(person_key=person_key, text=None, image_path=image_path)
            self.sync_base_with_cli(entry)
            return self.service.entry_reply(entry)

        return None

    def _should_handle_group_message(
        self,
        message_type: str,
        content: str,
        mentioned_bot: bool,
        bind_key: PersonKey | None,
    ) -> bool:
        if message_type == "image":
            return True
        if bind_key:
            return True
        if message_type != "text":
            return False
        if content in {"/help", "help", "帮助", "/今天", "今天", "/today"}:
            return mentioned_bot
        if self._looks_like_image_reference(content):
            return mentioned_bot
        if self._looks_like_food_record(content):
            return mentioned_bot
        return False

    def reply_text(self, message_id: str, text: str) -> None:
        self._run_cli(
            [
                "im",
                "+messages-reply",
                "--as",
                "bot",
                "--message-id",
                message_id,
                "--text",
                text,
                "--format",
                "json",
            ]
        )

    def download_message_image(self, message_id: str, image_key: str) -> Path:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        output = self.media_dir / f"{message_id}.jpg"
        self._run_cli(
            [
                "im",
                "+messages-resources-download",
                "--as",
                "bot",
                "--message-id",
                message_id,
                "--file-key",
                image_key,
                "--type",
                "image",
                "--output",
                output.as_posix(),
                "--format",
                "json",
            ]
        )
        return output

    def sync_base_with_cli(self, entry: FoodEntry) -> None:
        if self.sync_mode != "cli":
            return
        if not self.settings.feishu_bitable_app_token or not self.settings.feishu_bitable_table_id:
            return
        fields = food_entry_to_feishu_fields(self.settings, entry)
        self._run_cli(
            [
                "base",
                "+record-upsert",
                "--as",
                "bot",
                "--base-token",
                self.settings.feishu_bitable_app_token,
                "--table-id",
                self.settings.feishu_bitable_table_id,
                "--json",
                json.dumps(fields, ensure_ascii=False),
                "--format",
                "json",
            ]
        )

    def _run_cli(self, args: list[str]) -> str:
        result = subprocess.run(
            [*self.lark_cli, *args],
            check=False,
            text=True,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def _resolve_person(self, sender_id: str) -> PersonKey | None:
        for key, person in self.settings.people.items():
            if person.feishu_open_id and person.feishu_open_id == sender_id:
                return key  # type: ignore[return-value]
        return self.service.db.resolve_feishu_user(sender_id)

    def _match_bind_command(self, message_type: str, content: str) -> PersonKey | None:
        if message_type != "text":
            return None
        normalized = content.strip().replace(" ", "")
        if normalized in {"/我是小张", "我是小张", "小张", "绑定小张", "小张是我"}:
            return "me"
        if normalized in {"/我是小韩", "我是小韩", "小韩", "绑定小韩", "小韩是我"}:
            return "gf"
        return None

    def _extract_image_key(self, content: str) -> str | None:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                image_key = parsed.get("image_key")
                if image_key:
                    return str(image_key)
        except json.JSONDecodeError:
            pass

        match = IMAGE_KEY_PATTERN.search(content)
        return match.group(0) if match else None

    def _looks_like_image_reference(self, content: str) -> bool:
        normalized = content.replace(" ", "")
        return any(
            keyword in normalized
            for keyword in [
                "看图",
                "看图片",
                "看我发的图",
                "看我发的图片",
                "上一张",
                "上张图",
                "这张图",
                "这个图",
                "图片",
                "图里",
            ]
        )

    def _looks_like_food_record(self, content: str) -> bool:
        normalized = content.replace(" ", "")
        if len(normalized) < 3:
            return False
        keywords = [
            "早餐",
            "早饭",
            "午餐",
            "午饭",
            "晚餐",
            "晚饭",
            "夜宵",
            "加餐",
            "吃了",
            "喝了",
            "一碗",
            "一份",
            "一个",
            "一杯",
            "半碗",
            "半份",
        ]
        return any(keyword in normalized for keyword in keywords)

    def _mentioned_person_key(self, content: str) -> PersonKey | None:
        normalized = content.replace(" ", "")
        if "小韩" in normalized or "女朋友" in normalized:
            return "gf"
        if "小张" in normalized or "我的" in normalized or "我发" in normalized:
            return "me"
        return None

    def _strip_leading_mention(self, content: str) -> str:
        text = content.strip()
        if not text.startswith("@"):
            return text
        # Feishu's rendered content is commonly "@BotName command".
        match = re.match(r"^@\S+\s+(.*)$", text, flags=re.S)
        return match.group(1).strip() if match else text

    def _has_leading_mention(self, content: str) -> bool:
        return content.strip().startswith("@")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    FeishuCliBridge(load_settings()).run_stdin_loop()


def _split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt" and parts and parts[0] == "npx":
        parts[0] = "npx.cmd"
    return parts


if __name__ == "__main__":
    main()
