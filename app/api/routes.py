"""HTTP API 라우트 — /api/health, /api/languages, /api/queue, /api/translate.

동시성: 단일 T4 GPU는 파이프라인을 한 번에 하나만 처리해야 한다(메모리/경합).
manga-image-translator 의 요청 큐 패턴을 인프로세스로 단순화 —
세마포어(1)로 직렬화하고 대기 인원을 노출한다. (진행률 스트리밍은 Phase 3)

요청은 multipart: `file`(이미지) + `options`(PipelineOptions JSON, 선택).
"""
from __future__ import annotations

import asyncio
import traceback
import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from loguru import logger

from app.pipeline.orchestrator import pipeline, PipelineStageError
from app.schemas.options import PipelineOptions
from app.schemas.translation import SourceLang, TranslateResponse

router = APIRouter(prefix="/api")

# 단일 GPU 직렬화 + 대기 인원 카운터
_gpu_semaphore = asyncio.Semaphore(1)
_waiting = 0


@router.get("/health")
async def health() -> dict:
    from app.models.registry import registry
    return {"status": "ok", "models": registry.status()}


@router.get("/languages")
async def languages() -> dict:
    return {"source": [lang.value for lang in SourceLang], "target": ["ko"]}


@router.get("/queue")
async def queue() -> dict:
    """현재 대기/처리 중 상태 (프론트 진행 표시용)."""
    return {"waiting": _waiting, "busy": _gpu_semaphore.locked()}


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    file: UploadFile = File(...),
    options: str = Form("{}"),
) -> TranslateResponse:
    global _waiting
    opts = PipelineOptions.model_validate_json(options)
    image_bytes = await file.read()
    request_id = uuid.uuid4().hex

    _waiting += 1
    try:
        async with _gpu_semaphore:        # 한 번에 하나만 GPU 사용
            # 무거운 추론(GPU/CPU bound)은 스레드풀에서 — 이벤트 루프 블로킹 방지
            return await run_in_threadpool(
                pipeline.run,
                image_bytes=image_bytes,
                options=opts,
                request_id=request_id,
            )
    except PipelineStageError as e:
        # 어느 구간에서 실패했는지 응답 본문에 담아 돌려준다 (노트북 r.text 에서 바로 확인)
        logger.error(f"[{request_id}] '{e.stage}' 단계 실패\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={
            "error": "pipeline_stage_failed",
            "stage": e.stage,
            "detail": f"{type(e.original).__name__}: {e.original}",
            "request_id": request_id,
        })
    except Exception as e:
        logger.error(f"[{request_id}] 알 수 없는 오류\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={
            "error": "internal_error",
            "detail": f"{type(e).__name__}: {e}",
            "request_id": request_id,
        })
    finally:
        _waiting -= 1
