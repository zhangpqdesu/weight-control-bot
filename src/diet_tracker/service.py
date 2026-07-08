from __future__ import annotations

from datetime import date, datetime
import os
from pathlib import Path
import sys
import time

from .config import Settings
from .db import DietDatabase
from .feishu import FeishuBitableClient
from .llm_client import NutritionAnalyzer
from .models import FoodEntry, PersonKey


class DietTrackerService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = DietDatabase(settings.database_path)
        self.analyzer = NutritionAnalyzer(settings)
        self.feishu = FeishuBitableClient(settings)

    def add_food(self, person_key: PersonKey, text: str | None, image_path: Path | None) -> FoodEntry:
        t0 = time.perf_counter()
        print(
            f"analysis_start person={person_key} has_text={bool(text)} has_image={bool(image_path)}",
            file=sys.stderr,
            flush=True,
        )
        estimate = self.analyzer.analyze(text=text, image_path=image_path)
        print(
            f"analysis_done person={person_key} elapsed={time.perf_counter() - t0:.2f}s",
            file=sys.stderr,
            flush=True,
        )
        entry = FoodEntry(
            person_key=person_key,
            eaten_at=datetime.now(),
            raw_text=text,
            image_path=str(image_path) if image_path else None,
            estimate=estimate,
        )
        entry.id = self.db.add_entry(entry)
        self._sync_feishu(entry)
        return entry

    def _sync_feishu(self, entry: FoodEntry) -> None:
        if os.getenv("FEISHU_SYNC_MODE", "api").lower() == "cli":
            return
        if not entry.id or not self.feishu.enabled():
            return
        record_id = self.feishu.create_food_record(entry)
        self.db.mark_feishu_synced(entry.id, record_id)

    def today_reply(self, person_key: PersonKey) -> str:
        person = self.settings.people[person_key]
        summary = self.db.daily_summary(person_key, date.today(), person.daily_target_kcal)
        return (
            f"{person.display_name}今天已记录 {summary.entry_count} 餐\n"
            f"摄入：{summary.consumed_kcal}/{summary.target_kcal} kcal\n"
            f"剩余：{summary.remaining_kcal} kcal\n"
            f"蛋白质 {summary.protein_g}g | 碳水 {summary.carbs_g}g | 脂肪 {summary.fat_g}g"
        )

    def entry_reply(self, entry: FoodEntry) -> str:
        e = entry.estimate
        summary = self.db.daily_summary(
            entry.person_key,
            date.today(),
            self.settings.people[entry.person_key].daily_target_kcal,
        )
        return (
            f"已记录：{e.dish_name}\n"
            f"估算：{e.calories_kcal} kcal\n"
            f"蛋白质 {e.protein_g}g | 碳水 {e.carbs_g}g | 脂肪 {e.fat_g}g\n"
            f"份量：{e.portion_description}\n"
            f"可信度：{round(e.confidence * 100)}%\n"
            f"今天合计：{summary.consumed_kcal}/{summary.target_kcal} kcal，剩余 {summary.remaining_kcal} kcal"
        )
