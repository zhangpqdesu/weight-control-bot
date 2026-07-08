from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from .config import Settings
from .models import NutritionEstimate


SYSTEM_PROMPT = """你是一个严谨的饮食热量和营养估算助手。
请根据用户提供的中文描述和/或餐食图片，估算这一餐的总热量与宏量营养。
要求：
1. 优先按中国常见食物份量估算。
2. 图片中看不清或无法确认的部分，要在 reasoning 中说明不确定性。
3. 输出必须是 JSON，不要使用 Markdown。
4. calories_kcal 是整数；protein_g、carbs_g、fat_g、fiber_g 是克数。
5. confidence 必须是 0 到 1 的数字，不能写“高/中/低”等中文。
6. 必须包含这些字段：dish_name, portion_description, calories_kcal, protein_g, carbs_g, fat_g, fiber_g, confidence, reasoning。
"""


class NutritionAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(self, text: str | None, image_path: Path | None) -> NutritionEstimate:
        if not self.settings.llm_api_key:
            raise RuntimeError("Missing LLM_API_KEY in .env")

        user_content: list[dict[str, object]] = []
        if text:
            user_content.append({"type": "text", "text": text})
        if image_path:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._image_data_url(image_path)},
                }
            )
        if not user_content:
            raise ValueError("Provide text or image_path.")

        system_prompt = self._system_prompt()
        response = httpx.post(
            f"{self.settings.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
            },
            timeout=90,
        )
        if response.status_code == 401:
            raise RuntimeError(
                "MiMo/OpenAI-compatible API rejected the key. "
                "Check LLM_API_KEY and whether the token plan is active."
            )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        return NutritionEstimate.model_validate(json.loads(content))

    def _image_data_url(self, path: Path) -> str:
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _system_prompt(self) -> str:
        profile_path = self.settings.agent_profile_path
        if not profile_path.exists():
            return SYSTEM_PROMPT
        profile = profile_path.read_text(encoding="utf-8").strip()
        if not profile:
            return SYSTEM_PROMPT
        return f"{SYSTEM_PROMPT}\n\n以下是用户自定义的长期偏好和估算规则：\n{profile}"
