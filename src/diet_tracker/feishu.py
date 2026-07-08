from __future__ import annotations

import httpx

from .config import Settings
from .feishu_fields import food_entry_to_feishu_fields
from .models import FoodEntry


class FeishuBitableClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None

    def enabled(self) -> bool:
        return bool(
            self.settings.feishu_enabled
            and self.settings.feishu_app_id
            and self.settings.feishu_app_secret
            and self.settings.feishu_bitable_app_token
            and self.settings.feishu_bitable_table_id
        )

    def create_food_record(self, entry: FoodEntry) -> str:
        token = self._tenant_access_token()
        url = (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.settings.feishu_bitable_app_token}/tables/"
            f"{self.settings.feishu_bitable_table_id}/records"
        )
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"fields": food_entry_to_feishu_fields(self.settings, entry)},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu create record failed: {payload}")
        return payload["data"]["record"]["record_id"]

    def _tenant_access_token(self) -> str:
        if self._token:
            return self._token
        response = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self.settings.feishu_app_id,
                "app_secret": self.settings.feishu_app_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu token failed: {payload}")
        self._token = payload["tenant_access_token"]
        return self._token
