from __future__ import annotations

import json

from diet_tracker.config import load_settings
from diet_tracker.feishu_cli_bridge import FeishuCliBridge


def test_group_message_gate_ignores_chatter(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())

    assert not bridge._should_handle_group_message("text", "😭😭😭", False, None)
    assert not bridge._should_handle_group_message("text", "我看看什么情况", False, None)


def test_group_message_gate_requires_mention_for_food_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())

    assert not bridge._should_handle_group_message("text", "午饭 一碗面", False, None)
    assert bridge._should_handle_group_message("text", "午饭 一碗面", True, None)
    assert bridge._should_handle_group_message("text", "我的午饭", True, None)
    assert bridge._strip_leading_mention("@减肥机器人 午饭 一碗面") == "午饭 一碗面"
    assert bridge._strip_mentions("看图@减肥机器人") == "看图"
    assert bridge._has_mention("看图@减肥机器人")


def test_mentioned_person_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())

    assert bridge._mentioned_person_key("小韩的午饭是最近的图片") == "gf"
    assert bridge._mentioned_person_key("看我的图片") == "me"


def test_bind_recent_image_sender_command(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())

    assert bridge._match_bind_recent_image_sender_command("text", "把上一张图绑定为小韩") == "gf"
    assert bridge._match_bind_recent_image_sender_command("text", "刚才的图是小张") == "me"
    assert bridge._match_bind_recent_image_sender_command("text", "绑定小韩") is None


def test_resolve_context_image_for_meal_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())
    bridge.service.db.bind_feishu_user("ou_zhang", "me", "小张")
    bridge.service.db.remember_feishu_image("ou_zhang", "oc_room", "om_1", "data/lunch.jpg")

    person_key, image_path = bridge._resolve_context_image(
        person_key="me",
        sender_id="ou_zhang",
        chat_id="oc_room",
        chat_type="group",
        content="我的午饭",
    )

    assert person_key == "me"
    assert image_path == "data/lunch.jpg"


def test_feishu_json_text_mentions_are_detected(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())
    raw_content = json.dumps(
        {
            "text": "我的午饭",
            "mentions": [{"name": "减肥机器人"}],
        },
        ensure_ascii=False,
    )

    assert bridge._text_content(raw_content) == "我的午饭"
    assert bridge._event_mentions_bot({}, raw_content, "我的午饭")


def test_group_context_text_can_use_recent_sender_image_without_mention(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())
    bridge.service.db.remember_feishu_image("ou_zhang", "oc_room", "om_1", "data/lunch.jpg")

    assert bridge._should_handle_group_context_text(
        sender_id="ou_zhang",
        chat_id="oc_room",
        message_type="text",
        content="我的午饭",
    )
    assert not bridge._should_handle_group_context_text(
        sender_id="ou_other",
        chat_id="oc_room",
        message_type="text",
        content="我的午饭",
    )
