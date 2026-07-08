from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .models import DailySummary, FoodEntry, NutritionEstimate, PersonKey


SCHEMA = """
CREATE TABLE IF NOT EXISTS food_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_key TEXT NOT NULL,
    eaten_at TEXT NOT NULL,
    raw_text TEXT,
    image_path TEXT,
    dish_name TEXT NOT NULL,
    portion_description TEXT NOT NULL,
    calories_kcal INTEGER NOT NULL,
    protein_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    fiber_g REAL NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    model_payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_food_entries_person_date
ON food_entries(person_key, eaten_at);

CREATE TABLE IF NOT EXISTS feishu_user_bindings (
    open_id TEXT PRIMARY KEY,
    person_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feishu_recent_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    open_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    image_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feishu_recent_images_lookup
ON feishu_recent_images(open_id, chat_id, created_at);
"""


class DietDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(conn, "food_entries", "feishu_record_id", "TEXT")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

    def add_entry(self, entry: FoodEntry) -> int:
        estimate = entry.estimate
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO food_entries (
                    person_key, eaten_at, raw_text, image_path, dish_name,
                    portion_description, calories_kcal, protein_g, carbs_g,
                    fat_g, fiber_g, confidence, reasoning, model_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.person_key,
                    entry.eaten_at.isoformat(),
                    entry.raw_text,
                    entry.image_path,
                    estimate.dish_name,
                    estimate.portion_description,
                    estimate.calories_kcal,
                    estimate.protein_g,
                    estimate.carbs_g,
                    estimate.fat_g,
                    estimate.fiber_g,
                    estimate.confidence,
                    estimate.reasoning,
                    json.dumps(estimate.model_dump(), ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def mark_feishu_synced(self, entry_id: int, record_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE food_entries SET feishu_record_id = ? WHERE id = ?",
                (record_id, entry_id),
            )

    def bind_feishu_user(self, open_id: str, person_key: PersonKey, display_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feishu_user_bindings (open_id, person_key, display_name, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(open_id) DO UPDATE SET
                    person_key = excluded.person_key,
                    display_name = excluded.display_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (open_id, person_key, display_name),
            )

    def resolve_feishu_user(self, open_id: str) -> PersonKey | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT person_key FROM feishu_user_bindings WHERE open_id = ?",
                (open_id,),
            ).fetchone()
        if not row:
            return None
        person_key = row["person_key"]
        return person_key if person_key in {"me", "gf"} else None

    def remember_feishu_image(
        self,
        open_id: str,
        chat_id: str,
        message_id: str,
        image_path: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feishu_recent_images (open_id, chat_id, message_id, image_path)
                VALUES (?, ?, ?, ?)
                """,
                (open_id, chat_id, message_id, image_path),
            )

    def latest_feishu_image(self, open_id: str, chat_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT image_path FROM feishu_recent_images
                WHERE open_id = ?
                  AND chat_id = ?
                  AND created_at >= datetime('now', '-15 minutes')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (open_id, chat_id),
            ).fetchone()
        return str(row["image_path"]) if row else None

    def latest_feishu_image_in_chat(self, chat_id: str) -> tuple[str, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT open_id, image_path FROM feishu_recent_images
                WHERE chat_id = ?
                  AND created_at >= datetime('now', '-15 minutes')
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        if not row:
            return None
        return str(row["open_id"]), str(row["image_path"])

    def list_entries(self, person_key: PersonKey, day: date) -> list[FoodEntry]:
        start = datetime.combine(day, datetime.min.time()).isoformat()
        end = datetime.combine(day, datetime.max.time()).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM food_entries
                WHERE person_key = ? AND eaten_at BETWEEN ? AND ?
                ORDER BY eaten_at ASC
                """,
                (person_key, start, end),
            ).fetchall()

        return [self._row_to_entry(row) for row in rows]

    def daily_summary(self, person_key: PersonKey, day: date, target_kcal: int) -> DailySummary:
        entries = self.list_entries(person_key, day)
        consumed = sum(entry.estimate.calories_kcal for entry in entries)
        return DailySummary(
            person_key=person_key,
            date=day.isoformat(),
            target_kcal=target_kcal,
            consumed_kcal=consumed,
            remaining_kcal=target_kcal - consumed,
            protein_g=round(sum(entry.estimate.protein_g for entry in entries), 1),
            carbs_g=round(sum(entry.estimate.carbs_g for entry in entries), 1),
            fat_g=round(sum(entry.estimate.fat_g for entry in entries), 1),
            entry_count=len(entries),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> FoodEntry:
        estimate = NutritionEstimate(
            dish_name=row["dish_name"],
            portion_description=row["portion_description"],
            calories_kcal=row["calories_kcal"],
            protein_g=row["protein_g"],
            carbs_g=row["carbs_g"],
            fat_g=row["fat_g"],
            fiber_g=row["fiber_g"],
            confidence=row["confidence"],
            reasoning=row["reasoning"],
        )
        return FoodEntry(
            id=row["id"],
            person_key=row["person_key"],
            eaten_at=datetime.fromisoformat(row["eaten_at"]),
            raw_text=row["raw_text"],
            image_path=row["image_path"],
            estimate=estimate,
        )
