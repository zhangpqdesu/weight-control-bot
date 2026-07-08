from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


PersonKey = Literal["me", "gf"]


class NutritionEstimate(BaseModel):
    dish_name: str = Field(description="Short Chinese meal name.")
    portion_description: str
    calories_kcal: int = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float = Field(ge=0, default=0)
    confidence: float = Field(ge=0, le=1)
    reasoning: str

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> float:
        if isinstance(value, str):
            value = value.strip()
            mapping = {
                "高": 0.85,
                "较高": 0.8,
                "中等": 0.6,
                "中": 0.6,
                "较低": 0.35,
                "低": 0.25,
            }
            if value in mapping:
                return mapping[value]
            if value.endswith("%"):
                return float(value[:-1]) / 100
        return float(value)


class FoodEntry(BaseModel):
    id: int | None = None
    person_key: PersonKey
    eaten_at: datetime
    raw_text: str | None = None
    image_path: str | None = None
    estimate: NutritionEstimate


class DailySummary(BaseModel):
    person_key: PersonKey
    date: str
    target_kcal: int
    consumed_kcal: int
    remaining_kcal: int
    protein_g: float
    carbs_g: float
    fat_g: float
    entry_count: int
