"""Phase 1 — 오케스트레이터 end-to-end 검증 (GPU/네트워크 없이).

GPU 가 필요한 단계(감지·OCR)와 외부 호출(Gemini)만 가짜로 대체하고,
나머지(마스크·인페인팅 none·식자·오케스트레이션)는 실제 코드로 돌려
**파이프라인이 유효한 결과 이미지를 만들어내는지** 확인한다.
"""
from __future__ import annotations

import io

from PIL import Image

from app.pipeline import detection, ocr, orchestrator, translation
from app.schemas.options import InpainterName, PipelineOptions
from app.schemas.translation import BlockType, SourceLang, TextBlock


def _png_bytes(w=120, h=80):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_pipeline_end_to_end_without_models(monkeypatch):
    # 1) 감지: 합성 블록 1개 (말풍선 박스 포함)
    def fake_detect(img, opts):
        return [TextBlock(id=0, text_bbox=(20, 20, 100, 60),
                          bubble_bbox=(15, 15, 105, 65), type=BlockType.TEXT_BUBBLE, score=0.99)]

    # 2) OCR: 원문 채우기
    def fake_recognize(img, blocks, source_lang, opts):
        for b in blocks:
            b.original_text = "こんにちは"
            b.lang = SourceLang.JA
        return blocks

    # 3) 번역의 네트워크 호출만 대체 (나머지 _to_json/_apply_json/_validate 는 실제)
    def fake_call(system_prompt, user_prompt, opts, image=None):
        return '{"block_0": "안녕하세요"}'

    monkeypatch.setattr(detection, "detect", fake_detect)
    monkeypatch.setattr(ocr, "recognize", fake_recognize)
    monkeypatch.setattr(translation, "_call_gemini", fake_call)

    opts = PipelineOptions(source_lang=SourceLang.JA)
    opts.inpaint.inpainter = InpainterName.NONE   # 모델 없이 통과

    resp = orchestrator.pipeline.run(_png_bytes(), opts, request_id="test")

    # 결과 검증
    assert resp.result_image.startswith("data:image/png;base64,")
    assert resp.source_lang is SourceLang.JA and resp.target_lang == "ko"
    assert len(resp.blocks) == 1
    assert resp.blocks[0].original_text == "こんにちは"
    assert resp.blocks[0].translated_text == "안녕하세요"
    # 모든 단계 타이밍 기록됨
    assert {"detection", "segmentation", "ocr", "inpaint", "translate", "render"} <= set(resp.timing_ms)
