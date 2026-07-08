from __future__ import annotations

from datetime import datetime

from .config import Settings
from .models import FoodEntry


def food_entry_to_feishu_fields(settings: Settings, entry: FoodEntry) -> dict[str, object]:
    estimate = entry.estimate
    person = settings.people[entry.person_key].display_name
    return {
        "日期": _to_feishu_date(entry.eaten_at),
        "时间": entry.eaten_at.strftime("%H:%M"),
        "人": person,
        "餐食": estimate.dish_name,
        "份量": estimate.portion_description,
        "热量kcal": estimate.calories_kcal,
        "蛋白质g": estimate.protein_g,
        "碳水g": estimate.carbs_g,
        "脂肪g": estimate.fat_g,
        "膳食纤维g": estimate.fiber_g,
        "可信度": round(estimate.confidence, 2),
        "原始输入": entry.raw_text or "",
        "图片路径": entry.image_path or "",
        "说明": estimate.reasoning,
    }


def _to_feishu_date(value: datetime) -> int:
    return int(value.timestamp() * 1000)

