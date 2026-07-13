from __future__ import annotations

from diet_tracker.config import load_settings
from diet_tracker.intent_router import IntentContext, IntentRouter


def test_router_fallback_records_short_meal_with_recent_image(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    monkeypatch.setenv("LLM_API_KEY", "")
    router = IntentRouter(load_settings())

    intent = router.route(
        IntentContext(
            message_type="text",
            content="晚饭",
            chat_type="group",
            sender_person="me",
            mentioned_bot=True,
            sender_has_recent_image=True,
        )
    )

    assert intent.action == "record_food"
    assert intent.target_person == "me"
    assert intent.image_source == "sender"


def test_router_fallback_understands_freeform_girlfriend_context(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    monkeypatch.setenv("LLM_API_KEY", "")
    router = IntentRouter(load_settings())

    intent = router.route(
        IntentContext(
            message_type="text",
            content="这个是我女朋友刚发的",
            chat_type="group",
            sender_person="me",
            mentioned_bot=True,
            chat_has_recent_image=True,
            gf_has_recent_image=True,
        )
    )

    assert intent.action == "record_food"
    assert intent.target_person == "gf"
    assert intent.image_source in {"target_person", "latest_in_chat"}


def test_router_fallback_treats_first_person_as_sender_not_internal_me(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    monkeypatch.setenv("LLM_API_KEY", "")
    router = IntentRouter(load_settings())

    intent = router.route(
        IntentContext(
            message_type="text",
            content="我吃了一个盒饭",
            chat_type="group",
            sender_person="gf",
            mentioned_bot=True,
        )
    )

    assert intent.action == "record_food"
    assert intent.target_person == "gf"


def test_router_normalize_overrides_model_target_with_sender_for_first_person(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    router = IntentRouter(load_settings())
    context = IntentContext(
        message_type="text",
        content="我吃了一个盒饭",
        chat_type="group",
        sender_person="gf",
        mentioned_bot=True,
    )
    intent = router.fallback(context)
    intent.target_person = "me"

    normalized = router._normalize(intent, context)

    assert normalized.target_person == "gf"


def test_router_fallback_clarifies_unclear_mentions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "diet.sqlite3"))
    monkeypatch.setenv("LLM_API_KEY", "")
    router = IntentRouter(load_settings())

    intent = router.route(
        IntentContext(
            message_type="text",
            content="你啊又发病了",
            chat_type="group",
            sender_person="me",
            mentioned_bot=True,
        )
    )

    assert intent.action == "clarify"
    assert intent.should_reply
