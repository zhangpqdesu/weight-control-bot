from __future__ import annotations

from datetime import date, datetime

from diet_tracker.db import DietDatabase
from diet_tracker.models import FoodEntry, NutritionEstimate


def test_add_entry_and_daily_summary(tmp_path):
    db = DietDatabase(tmp_path / "diet.sqlite3")
    estimate = NutritionEstimate(
        dish_name="牛肉面",
        portion_description="一大碗",
        calories_kcal=750,
        protein_g=32,
        carbs_g=95,
        fat_g=24,
        fiber_g=4,
        confidence=0.72,
        reasoning="按常见一大碗牛肉面估算。",
    )
    db.add_entry(
        FoodEntry(
            person_key="me",
            eaten_at=datetime.now(),
            raw_text="一大碗牛肉面",
            image_path=None,
            estimate=estimate,
        )
    )

    summary = db.daily_summary("me", date.today(), target_kcal=2600)

    assert summary.entry_count == 1
    assert summary.consumed_kcal == 750
    assert summary.remaining_kcal == 1850
    assert summary.protein_g == 32


def test_bind_and_resolve_feishu_user(tmp_path):
    db = DietDatabase(tmp_path / "diet.sqlite3")

    db.bind_feishu_user("ou_zhang", "me", "小张")
    db.bind_feishu_user("ou_han", "gf", "小韩")

    assert db.resolve_feishu_user("ou_zhang") == "me"
    assert db.resolve_feishu_user("ou_han") == "gf"
    assert db.resolve_feishu_user("ou_unknown") is None


def test_remember_and_find_latest_feishu_image(tmp_path):
    db = DietDatabase(tmp_path / "diet.sqlite3")
    db.bind_feishu_user("ou_zhang", "me", "小张")

    db.remember_feishu_image(
        open_id="ou_zhang",
        chat_id="oc_room",
        message_id="om_1",
        image_path="data/one.jpg",
    )
    db.remember_feishu_image(
        open_id="ou_zhang",
        chat_id="oc_room",
        message_id="om_2",
        image_path="data/two.jpg",
    )

    assert db.latest_feishu_image("ou_zhang", "oc_room") == "data/two.jpg"
    assert db.latest_feishu_image("ou_han", "oc_room") is None
    assert db.latest_feishu_image_in_chat("oc_room") == ("ou_zhang", "data/two.jpg")
    assert db.latest_feishu_image_for_person("me", "oc_room") == ("ou_zhang", "data/two.jpg")
    assert db.latest_feishu_image_for_person("gf", "oc_room") is None
