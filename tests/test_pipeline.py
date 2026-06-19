"""파이프라인 골격 / 데이터 계약 테스트.

모델이 필요 없는 부분(스키마, 이미지 유틸)부터 검증한다.
모델 단계 구현(Phase 1) 이후 통합 테스트를 추가한다.
"""
from __future__ import annotations

import io

from PIL import Image

from app.schemas.options import Backend, InpainterName, PipelineOptions
from app.schemas.translation import BlockType, SourceLang, TextBlock
from app.utils import image as imageutil


def _sample_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 16), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def test_textblock_defaults():
    block = TextBlock(id=0, text_bbox=(0, 0, 10, 10))
    assert block.type is BlockType.TEXT_BUBBLE
    assert block.bubble_bbox is None
    assert block.original_text is None
    assert block.translated_text is None


def test_source_lang_values():
    assert {l.value for l in SourceLang} == {"auto", "ja", "en", "zh"}


def test_image_load_and_crop():
    img = imageutil.load(_sample_png_bytes())
    assert img.size == (32, 16)
    assert imageutil.crop(img, (0, 0, 8, 8)).size == (8, 8)


def test_to_data_url_roundtrip():
    img = imageutil.load(_sample_png_bytes())
    url = imageutil.to_data_url(img)
    assert url.startswith("data:image/png;base64,")


def test_pipeline_options_defaults_from_empty_json():
    opts = PipelineOptions.model_validate_json("{}")
    assert opts.source_lang is SourceLang.AUTO
    assert opts.target_lang == "ko"
    assert opts.detection.confidence == 0.3
    assert opts.inpaint.inpainter is InpainterName.LAMA
    assert opts.render.rtl is True


def test_pipeline_options_partial_override():
    opts = PipelineOptions.model_validate_json(
        '{"source_lang": "ja", "ocr": {"backend": "torch"}}'
    )
    assert opts.source_lang is SourceLang.JA
    assert opts.ocr.backend is Backend.TORCH
    # 명시 안 한 값은 기본 유지
    assert opts.detection.backend is Backend.ONNX
