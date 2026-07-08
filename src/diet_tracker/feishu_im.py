from __future__ import annotations

import json
from pathlib import Path

import httpx

from .config import Settings


class FeishuImClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None

    def tenant_access_token(self) -> str:
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

    def reply_text(self, message_id: str, text: str) -> None:
        response = httpx.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            headers={
                "Authorization": f"Bearer {self.tenant_access_token()}",
                "Content-Type": "application/json",
            },
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu reply failed: {payload}")

    def download_message_image(self, message_id: str, image_key: str, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{message_id}.jpg"
        response = httpx.get(
            "https://open.feishu.cn/open-apis/im/v1/messages/"
            f"{message_id}/resources/{image_key}",
            params={"type": "image"},
            headers={"Authorization": f"Bearer {self.tenant_access_token()}"},
            timeout=60,
        )
        response.raise_for_status()
        target.write_bytes(response.content)
        return target

