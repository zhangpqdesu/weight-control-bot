from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class PersonConfig:
    key: str
    display_name: str
    wechat_name: str
    daily_target_kcal: int
    feishu_open_id: str = ""


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    database_path: Path
    agent_profile_path: Path
    wechat_group_name: str
    people: dict[str, PersonConfig]
    feishu_enabled: bool
    feishu_app_id: str
    feishu_app_secret: str
    feishu_verification_token: str
    feishu_encrypt_key: str
    feishu_bitable_app_token: str
    feishu_bitable_table_id: str


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    return int(raw)


def load_settings() -> Settings:
    people = {
        "me": PersonConfig(
            key="me",
            display_name=os.getenv("ME_DISPLAY_NAME", "小张"),
            wechat_name=os.getenv("ME_USER_NAME", ""),
            daily_target_kcal=_int_env("ME_DAILY_TARGET_KCAL", 2600),
            feishu_open_id=os.getenv("FEISHU_ME_OPEN_ID", ""),
        ),
        "gf": PersonConfig(
            key="gf",
            display_name=os.getenv("GF_DISPLAY_NAME", "小韩"),
            wechat_name=os.getenv("GF_USER_NAME", ""),
            daily_target_kcal=_int_env("GF_DAILY_TARGET_KCAL", 1600),
            feishu_open_id=os.getenv("FEISHU_GF_OPEN_ID", ""),
        ),
    }

    return Settings(
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
        database_path=Path(os.getenv("DATABASE_PATH", "data/diet_tracker.sqlite3")),
        agent_profile_path=Path(os.getenv("AGENT_PROFILE_PATH", "data/agent.md")),
        wechat_group_name=os.getenv("WECHAT_GROUP_NAME", ""),
        people=people,
        feishu_enabled=os.getenv("FEISHU_ENABLED", "false").lower() == "true",
        feishu_app_id=os.getenv("FEISHU_APP_ID", ""),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
        feishu_encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
        feishu_bitable_app_token=os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
        feishu_bitable_table_id=os.getenv("FEISHU_BITABLE_TABLE_ID", ""),
    )
