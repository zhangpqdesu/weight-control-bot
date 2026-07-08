from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
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
把上一张图绑定为小韩 绑定最近发图的人为小韩
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
            received_at = time.perf_counter()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                print(
                    "event_received "
                    f"message_id={event.get('message_id') or event.get('id') or ''} "
                    f"type={event.get('message_type') or ''} "
                    f"chat_type={event.get('chat_type') or ''}",
                    file=sys.stderr,
                    flush=True,
                )
                self.handle_event(event)
                print(
                    "event_done "
                    f"message_id={event.get('message_id') or event.get('id') or ''} "
                    f"elapsed={time.perf_counter() - received_at:.2f}s",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:
                print(f"failed to handle event: {exc}", file=sys.stderr, flush=True)

    def handle_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("message_id") or event.get("id") or "")
        message_type = str(event.get("message_type") or "")
        sender_id = str(event.get("sender_id") or "")
        chat_id = str(event.get("chat_id") or "")
        chat_type = str(event.get("chat_type") or "")
        raw_content = str(event.get("content") or "").strip()
        content = self._text_content(raw_content) if message_type == "text" else raw_content

        if not message_id or not sender_id:
            return

        mentioned_bot = self._event_mentions_bot(event, raw_content, content)
        clean_content = self._strip_mentions(content)

        bind_key = self._match_bind_command(message_type, clean_content)
        if bind_key:
            person = self.settings.people[bind_key]
            self.service.db.bind_feishu_user(sender_id, bind_key, person.display_name)
            self.reply_text(
                message_id,
                f"已绑定：{person.display_name}\n以后你的饮食会记录到 {person.display_name} 的每日统计里。",
            )
            return

        bind_recent_image_key = self._match_bind_recent_image_sender_command(
            message_type,
            clean_content,
        )
        if bind_recent_image_key:
            reply = self._bind_recent_image_sender(chat_id, bind_recent_image_key)
            self.reply_text(message_id, reply)
            return

        if chat_type == "group" and not self._should_handle_group_message(
            message_type=message_type,
            content=clean_content,
            mentioned_bot=mentioned_bot,
            bind_key=bind_key,
        ):
            if not self._should_handle_group_context_text(
                sender_id=sender_id,
                chat_id=chat_id,
                message_type=message_type,
                content=clean_content,
            ):
                print(
                    "event_ignored "
                    f"message_id={message_id} "
                    f"mentioned={mentioned_bot} "
                    f"content={clean_content[:80]!r}",
                    file=sys.stderr,
                    flush=True,
                )
                return

        if message_type == "image" and chat_type == "group":
            t0 = time.perf_counter()
            self._cache_image(sender_id, chat_id, message_id, content)
            print(
                f"image_cached message_id={message_id} elapsed={time.perf_counter() - t0:.2f}s",
                file=sys.stderr,
                flush=True,
            )
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
            target_person_key, image_path = self._resolve_context_image(
                person_key=person_key,
                sender_id=sender_id,
                chat_id=chat_id,
                chat_type=chat_type,
                content=content,
            )
            if self._looks_like_image_reference(content):
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
            entry = self.service.add_food(
                person_key=target_person_key,
                text=content,
                image_path=Path(image_path) if image_path else None,
            )
            self.sync_base_with_cli(entry)
            return self.service.entry_reply(entry)

        if message_type == "image":
            image_path = self._cache_image(sender_id, chat_id, message_id, content)
            if chat_type == "group":
                return None
            entry = self.service.add_food(person_key=person_key, text=None, image_path=image_path)
            self.sync_base_with_cli(entry)
            return self.service.entry_reply(entry)

        return None

    def _resolve_context_image(
        self,
        person_key: PersonKey,
        sender_id: str,
        chat_id: str,
        chat_type: str,
        content: str,
    ) -> tuple[PersonKey, str | None]:
        target_person_key = self._mentioned_person_key(content) or person_key
        image_path: str | None = None

        if target_person_key != person_key:
            latest_for_person = self.service.db.latest_feishu_image_for_person(
                target_person_key,
                chat_id,
            )
            if latest_for_person:
                _, image_path = latest_for_person

        if not image_path:
            image_path = self.service.db.latest_feishu_image(sender_id, chat_id)

        if not image_path and chat_type == "group":
            latest_in_chat = self.service.db.latest_feishu_image_in_chat(chat_id)
            if latest_in_chat:
                image_sender_id, image_path = latest_in_chat
                target_person_key = (
                    self._mentioned_person_key(content)
                    or self._resolve_person(image_sender_id)
                    or person_key
                )

        return target_person_key, image_path

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
        if self._match_bind_recent_image_sender_command(message_type, content):
            return mentioned_bot
        if self._looks_like_food_record(content):
            return mentioned_bot
        return False

    def _should_handle_group_context_text(
        self,
        sender_id: str,
        chat_id: str,
        message_type: str,
        content: str,
    ) -> bool:
        if message_type != "text":
            return False
        if not self._looks_like_food_record(content):
            return False
        return self.service.db.latest_feishu_image(sender_id, chat_id) is not None

    def _cache_image(self, sender_id: str, chat_id: str, message_id: str, content: str) -> Path:
        image_key = self._extract_image_key(content)
        if not image_key:
            raise RuntimeError(
                "收到图片，但 CLI 事件里没有 image_key。"
                "请用 `lark-cli event schema im.message.receive_v1` 确认图片事件 content 格式。"
            )
        t0 = time.perf_counter()
        image_path = self.download_message_image(message_id, image_key)
        print(
            f"image_downloaded message_id={message_id} elapsed={time.perf_counter() - t0:.2f}s",
            file=sys.stderr,
            flush=True,
        )
        self.service.db.remember_feishu_image(
            open_id=sender_id,
            chat_id=chat_id,
            message_id=message_id,
            image_path=str(image_path),
        )
        return image_path

    def reply_text(self, message_id: str, text: str) -> None:
        t0 = time.perf_counter()
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
        print(
            f"reply_sent message_id={message_id} elapsed={time.perf_counter() - t0:.2f}s",
            file=sys.stderr,
            flush=True,
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

    def _match_bind_recent_image_sender_command(
        self,
        message_type: str,
        content: str,
    ) -> PersonKey | None:
        if message_type != "text":
            return None
        normalized = content.strip().replace(" ", "")
        if not any(keyword in normalized for keyword in ["上一张图", "最近图片", "最近的图", "刚才图片", "刚才的图"]):
            return None
        if "绑定" not in normalized and "是" not in normalized:
            return None
        if "小韩" in normalized or "女朋友" in normalized:
            return "gf"
        if "小张" in normalized or "我" in normalized:
            return "me"
        return None

    def _bind_recent_image_sender(self, chat_id: str, person_key: PersonKey) -> str:
        latest = self.service.db.latest_feishu_image_in_chat(chat_id)
        person = self.settings.people[person_key]
        if not latest:
            return f"没找到 15 分钟内的群图片，暂时没法绑定为 {person.display_name}。"
        image_sender_id, _ = latest
        self.service.db.bind_feishu_user(image_sender_id, person_key, person.display_name)
        return (
            f"已绑定最近发图的人为：{person.display_name}\n"
            f"以后这个 sender_id 的图片会优先记录到 {person.display_name}。"
        )

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
        meal_words = {"早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭", "夜宵", "加餐"}
        if normalized in meal_words:
            return True
        if len(normalized) < 2:
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
        return self._strip_mentions(content)

    def _strip_mentions(self, content: str) -> str:
        text = content.strip()
        text = re.sub(r"@\S+", " ", text, flags=re.S)
        return re.sub(r"\s+", " ", text).strip()

    def _has_leading_mention(self, content: str) -> bool:
        return self._has_mention(content)

    def _has_mention(self, content: str) -> bool:
        return "@" in content

    def _text_content(self, raw_content: str) -> str:
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return raw_content
        if isinstance(parsed, dict):
            text = parsed.get("text") or parsed.get("content")
            if isinstance(text, str):
                return text.strip()
        return raw_content

    def _event_mentions_bot(
        self,
        event: dict[str, Any],
        raw_content: str,
        text_content: str,
    ) -> bool:
        if self._has_mention(raw_content) or self._has_mention(text_content):
            return True
        if self._json_mentions(raw_content):
            return True
        return self._contains_nonempty_mention_field(event)

    def _json_mentions(self, raw_content: str) -> bool:
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return False
        return self._contains_nonempty_mention_field(parsed)

    def _contains_nonempty_mention_field(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).lower()
                if normalized_key in {"mentions", "mention", "at_users", "ats"}:
                    if child:
                        return True
                if self._contains_nonempty_mention_field(child):
                    return True
        if isinstance(value, list):
            return any(self._contains_nonempty_mention_field(item) for item in value)
        return False


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
