"""FastAPI 진입점 — API 라우터 등록 + 정적 프론트(/) 서빙."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
from app.utils.logging import setup_logging

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    if settings.warmup_on_startup:
        from app.models.registry import registry
        registry.warmup()          # 콜드스타트 단축용 사전 로딩
    yield


app = FastAPI(title="Manga Translator", version="0.1.0", lifespan=lifespan)
app.include_router(router)

# 정적 프론트(/)는 API 라우터 뒤에 마운트한다.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
