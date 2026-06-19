"""애플리케이션 설정 — .env 를 읽어 들인다."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),   # model_dir 등 'model_' 접두 필드 허용
    )

    # API 키 (커밋 금지 — .env / Colab userdata 로 주입)
    gemini_api_key: str = ""
    ngrok_authtoken: str = ""

    # 서버
    host: str = "0.0.0.0"
    port: int = 8000

    # 경로
    model_dir: Path = Path("./models")
    hf_home: Path = Path("./models/hf")

    # 번역
    target_lang: str = "ko"
    gemini_model: str = "gemini-2.0-flash"

    # 시작 시 모델 사전 로딩(콜드스타트 단축)
    warmup_on_startup: bool = False


settings = Settings()
