from __future__ import annotations

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
    assert bridge._strip_leading_mention("@减肥机器人 午饭 一碗面") == "午饭 一碗面"


def test_mentioned_person_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    bridge = FeishuCliBridge(load_settings())

    assert bridge._mentioned_person_key("小韩的午饭是最近的图片") == "gf"
    assert bridge._mentioned_person_key("看我的图片") == "me"
