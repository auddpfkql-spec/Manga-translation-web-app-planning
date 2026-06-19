"""파이프라인 실행 옵션 (요청 단위 통합 설정).

manga-image-translator 의 통합 Config 패턴을 우리 범위(JP/EN/ZH → KO)에 맞게 정리.
'무엇을'(source/target 언어)과 '어떻게'(단계별 백엔드·임계값)를 분리한다.
프론트는 multipart 의 `options` 필드에 이 JSON 을 실어 보낸다. (모든 필드 기본값 보유 → 빈 `{}` 도 유효)
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.translation import SourceLang


class Backend(str, Enum):
    ONNX = "onnx"     # 경량·고속 (기본)
    TORCH = "torch"


class InpainterName(str, Enum):
    LAMA = "lama"     # 망가 LaMa (기본)
    AOT = "aot"
    NONE = "none"


class DetectionOptions(BaseModel):
    confidence: float = 0.3        # RT-DETR 신뢰도 임계값
    detection_size: int = 2048     # 검출 입력 크기
    unclip_ratio: float = 2.3      # 텍스트 스켈레톤 → 박스 확장
    backend: Backend = Backend.ONNX


class OcrOptions(BaseModel):
    backend: Backend = Backend.ONNX


class InpaintOptions(BaseModel):
    inpainter: InpainterName = InpainterName.LAMA
    backend: Backend = Backend.ONNX


class TranslateOptions(BaseModel):
    model: str = "gemini-2.0-flash"
    use_image_context: bool = True   # 페이지 이미지 동봉(문맥 품질↑)
    skip_if_target: bool = True      # 이미 한국어면 건너뜀
    max_retries: int = 3             # 번역 후 검증 실패 시 재시도


class RenderOptions(BaseModel):
    font_family: str | None = None       # None 이면 기본 폰트
    min_font_size: int | None = None     # None 이면 (가로+세로)/200
    font_size_offset: int = 0
    alignment: str = "center"            # left | center | right
    outline: bool = True
    rtl: bool = True                     # 컷·블록 우→좌(망가)


class PipelineOptions(BaseModel):
    """요청 단위 파이프라인 설정. 언어는 top-level, 단계별 '방법'은 하위 객체."""

    source_lang: SourceLang = SourceLang.AUTO
    target_lang: str = "ko"
    detection: DetectionOptions = Field(default_factory=DetectionOptions)
    ocr: OcrOptions = Field(default_factory=OcrOptions)
    inpaint: InpaintOptions = Field(default_factory=InpaintOptions)
    translate: TranslateOptions = Field(default_factory=TranslateOptions)
    render: RenderOptions = Field(default_factory=RenderOptions)
