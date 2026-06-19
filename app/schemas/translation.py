"""파이프라인 전 단계가 공유하는 데이터 계약(스키마).

comic-translate 의 `TextBlock`(modules/utils/textblock.py)을 웹 API 에 맞게 정리한 것.
핵심 차용점:
  - 말풍선 박스(bubble_bbox)와 텍스트 박스(text_bbox)를 **분리** 저장
  - 정밀 인페인팅을 위한 세그멘테이션 폴리곤(segm_points)
  - 세로/가로(direction), 회전각(angle), 줄별 OCR(texts)
  - 식자 힌트(font_color, min/max_font_size, alignment, line_spacing)
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    """RT-DETR 감지 클래스. (class 0=bubble 자체는 bubble_bbox 로만 저장)"""

    TEXT_BUBBLE = "text_bubble"   # 말풍선 안 텍스트 (RT-DETR class 1)
    TEXT_FREE = "text_free"       # 말풍선 밖 텍스트/효과음 (RT-DETR class 2)


class SourceLang(str, Enum):
    AUTO = "auto"
    JA = "ja"
    EN = "en"
    ZH = "zh"


class Direction(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"         # 일본어 세로쓰기 등 — OCR 읽기 순서용(KO 출력은 항상 가로)


class TextBlock(BaseModel):
    """단일 텍스트 영역. 파이프라인을 따라가며 필드가 점진적으로 채워진다.

    좌표는 모두 원본 이미지 픽셀 기준 (x1, y1, x2, y2).
    """

    id: int

    # --- 감지 (detection) ---
    text_bbox: tuple[int, int, int, int]                  # 텍스트 영역
    bubble_bbox: tuple[int, int, int, int] | None = None  # 텍스트를 감싼 말풍선(있으면)
    type: BlockType = BlockType.TEXT_BUBBLE
    score: float = 0.0
    angle: float = 0.0                                    # 회전각(도)
    segm_points: list[tuple[int, int]] | None = None      # 정밀 마스크용 폴리곤

    # --- OCR ---
    original_text: str | None = None
    texts: list[str] = Field(default_factory=list)        # 줄별 원문
    lang: SourceLang | None = None
    direction: Direction = Direction.HORIZONTAL

    # --- 번역 (translation) ---
    translated_text: str | None = None

    # --- 식자 힌트 (rendering) ---
    font_color: tuple[int, int, int] | None = None        # (R, G, B)
    min_font_size: int | None = None
    max_font_size: int | None = None
    alignment: str = "center"                             # left | center | right
    line_spacing: float = 1.0


class TranslateResponse(BaseModel):
    request_id: str
    source_lang: SourceLang
    target_lang: str = "ko"
    result_image: str                                     # base64 data URL 또는 경로
    blocks: list[TextBlock] = Field(default_factory=list)
    timing_ms: dict[str, float] = Field(default_factory=dict)
