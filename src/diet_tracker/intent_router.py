from __future__ import annotations

import json
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .config import Settings
from .models import PersonKey


IntentAction = Literal[
    "record_food",
    "query_today",
    "bind_user",
    "bind_recent_image_sender",
    "help",
    "clarify",
    "ignore",
]

ImageSource = Literal["none", "sender", "target_person", "latest_in_chat"]


class IntentContext(BaseModel):
    message_type: str
    content: str
    chat_type: str
    sender_person: PersonKey | None = None
    mentioned_bot: bool = False
    sender_has_recent_image: bool = False
    chat_has_recent_image: bool = False
    me_has_recent_image: bool = False
    gf_has_recent_image: bool = False


class Intent(BaseModel):
    action: IntentAction = "ignore"
    target_person: PersonKey | None = None
    image_source: ImageSource = "none"
    meal_label: str | None = None
    normalized_text: str | None = None
    should_reply: bool = True
    clarification: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason: str = ""


ROUTER_PROMPT = """你是飞书群里的饮食记录机器人意图路由器。
你只输出 JSON，不要 Markdown。

可选 action：
- record_food：用户想记录饮食、饮料、零食、某一餐，或用最近图片估算热量。
- query_today：用户想查看今天统计、剩余热量、已吃多少。
- bind_user：用户声明“我是小张/我是小韩”等，把当前发送者绑定为某人。
- bind_recent_image_sender：用户想把最近发图的人绑定为某人。
- help：用户要帮助。
- clarify：用户 @ 了机器人但意图不够明确，需要问一句澄清。
- ignore：不需要回复。

字段：
- target_person: "me"、"gf" 或 null。小张=me，小韩/女朋友=gf。用户说“我/我的/我这顿”通常是 sender_person。
- image_source: "none"、"sender"、"target_person"、"latest_in_chat"。
- meal_label: 早餐/午饭/晚饭/加餐等，没有就 null。
- normalized_text: 给后续营养模型看的简短中文描述，保留用户原意。
- should_reply: ignore 时通常 false；其他通常 true。
- clarification: action=clarify 时要回复用户的话。
- confidence: 0 到 1。
- reason: 简短解释。

重要规则：
1. 如果 content 很短但像“晚饭”“午饭”“这个”“这顿”“帮我记一下”，且有最近图片，应当 record_food 并使用图片。
2. 如果 content 提到小韩/女朋友/她，target_person=gf。
3. 如果 content 提到小张，target_person=me。
4. 如果用户 @ 了机器人，不要轻易 ignore；不确定就 clarify。
5. 如果没有任何最近图片，但 content 是具体食物描述，也可以 record_food 且 image_source=none。
6. 如果群聊里未 @ 机器人，通常 ignore；图片缓存由外层处理，不由你处理。
7. 不要把闲聊、骂人、测试无意义文本记录成饮食；如果 @ 了但不是饮食/查询/绑定/help，则 clarify 或 ignore。
"""


class IntentRouter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def route(self, context: IntentContext) -> Intent:
        if not self.settings.llm_api_key:
            return self.fallback(context)
        try:
            response = httpx.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.llm_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": ROUTER_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                context.model_dump(),
                                ensure_ascii=False,
                            ),
                        },
                    ],
                },
                timeout=20,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return self._normalize(Intent.model_validate(json.loads(content)), context)
        except Exception:
            return self.fallback(context)

    def fallback(self, context: IntentContext) -> Intent:
        text = context.content.strip()
        normalized = text.replace(" ", "")
        explicit_target = self._explicit_target_from_text(normalized)
        target = explicit_target or context.sender_person
        meal_words = {"早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭", "夜宵", "加餐"}
        image_source: ImageSource = "none"
        if target == "gf" and context.sender_person != "gf" and context.gf_has_recent_image:
            image_source = "target_person"
        elif target == "me" and context.sender_person != "me" and context.me_has_recent_image:
            image_source = "target_person"
        elif context.sender_has_recent_image:
            image_source = "sender"
        elif target == "gf" and context.gf_has_recent_image:
            image_source = "target_person"
        elif target == "me" and context.me_has_recent_image:
            image_source = "target_person"
        elif context.chat_has_recent_image:
            image_source = "latest_in_chat"

        if normalized in {"/help", "help", "帮助"}:
            return Intent(action="help", confidence=1, reason="help command")
        if normalized in {"/今天", "今天", "/today", "今日统计", "剩余热量", "还剩多少"}:
            return Intent(
                action="query_today",
                target_person=target,
                confidence=0.9,
                reason="today summary command",
            )
        bind_target = self._bind_target_from_text(normalized)
        if bind_target:
            return Intent(
                action="bind_user",
                target_person=bind_target,
                confidence=0.95,
                reason="self binding command",
            )
        if ("绑定" in normalized or "是" in normalized) and image_source == "latest_in_chat":
            if "小韩" in normalized or "女朋友" in normalized:
                return Intent(
                    action="bind_recent_image_sender",
                    target_person="gf",
                    confidence=0.85,
                    reason="bind recent image sender",
                )
            if "小张" in normalized:
                return Intent(
                    action="bind_recent_image_sender",
                    target_person="me",
                    confidence=0.85,
                    reason="bind recent image sender",
                )
        if image_source != "none" and (
            normalized in meal_words
            or normalized in {"这个", "这顿", "这餐", "刚才", "刚刚", "上面", "帮我记一下", "记录一下"}
            or any(word in normalized for word in ["我的", "小韩", "女朋友", "午饭", "晚饭", "早餐"])
        ):
            return Intent(
                action="record_food",
                target_person=target,
                image_source=image_source,
                meal_label=normalized if normalized in meal_words else None,
                normalized_text=text,
                confidence=0.7,
                reason="recent image plus meal context",
            )
        if any(word in normalized for word in ["吃", "喝", "饭", "餐", "咖啡", "奶茶", "鸡", "蛋", "面", "米"]):
            return Intent(
                action="record_food",
                target_person=target,
                image_source=image_source,
                normalized_text=text,
                confidence=0.55,
                reason="food-like text",
            )
        if context.mentioned_bot:
            return Intent(
                action="clarify",
                target_person=target,
                clarification="这是要记录刚才那张图，还是查今天统计？",
                confidence=0.4,
                reason="mentioned bot but unclear",
            )
        return Intent(action="ignore", should_reply=False, reason="not addressed to bot")

    def _normalize(self, intent: Intent, context: IntentContext) -> Intent:
        explicit_target = self._explicit_target_from_text(context.content.replace(" ", ""))
        if explicit_target:
            intent.target_person = explicit_target
        elif context.sender_person:
            intent.target_person = context.sender_person
        elif not intent.target_person:
            intent.target_person = context.sender_person
        if not intent.normalized_text:
            intent.normalized_text = context.content
        if intent.action == "ignore":
            intent.should_reply = False
        if intent.image_source == "sender" and not context.sender_has_recent_image:
            intent.image_source = "none"
        if intent.image_source == "target_person":
            if intent.target_person == "me" and not context.me_has_recent_image:
                intent.image_source = "none"
            if intent.target_person == "gf" and not context.gf_has_recent_image:
                intent.image_source = "none"
        if intent.image_source == "latest_in_chat" and not context.chat_has_recent_image:
            intent.image_source = "none"
        return intent

    def _explicit_target_from_text(self, normalized: str) -> PersonKey | None:
        if "小韩" in normalized or "女朋友" in normalized:
            return "gf"
        if "小张" in normalized:
            return "me"
        return None

    def _bind_target_from_text(self, normalized: str) -> PersonKey | None:
        if normalized in {"/我是小张", "我是小张", "小张", "绑定小张", "小张是我"}:
            return "me"
        if normalized in {"/我是小韩", "我是小韩", "小韩", "绑定小韩", "小韩是我"}:
            return "gf"
        return None
