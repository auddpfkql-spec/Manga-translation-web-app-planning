"""3) OCR — 언어 라우팅.

comic-translate/modules/ocr/factory.py 의 언어→엔진 매핑을 따른다:
    일본어  → manga-ocr            (kha-white/manga-ocr-base)
    영어    → PP-OCRv5 (lang='en')
    중국어  → PP-OCRv5 (lang='ch')

auto 이면 기본 ja (manga 기준). direction 은 bbox 종횡비로 추정.
"""
from __future__ import annotations

from PIL import Image

from app.models.registry import registry
from app.schemas.options import OcrOptions
from app.schemas.translation import Direction, SourceLang, TextBlock
from app.utils import image as imageutil

# PaddleOCR lang 코드 매핑
_PPOCR_LANG: dict[str, str] = {"en": "en", "zh": "ch"}


def recognize(
    img: Image.Image,
    blocks: list[TextBlock],
    source_lang: SourceLang,
    opts: OcrOptions,
) -> list[TextBlock]:
    """각 블록 영역을 크롭해 OCR. 원문·언어·방향을 block 에 채워 반환."""
    for block in blocks:
        crop = imageutil.crop(img, block.text_bbox)
        if crop is None:
            continue

        # auto 이면 일본어로 간주 (만화 기본)
        lang = source_lang if source_lang != SourceLang.AUTO else SourceLang.JA

        if lang == SourceLang.JA:
            text = _run_manga_ocr(crop)
            lines: list[str] = [text] if text else []
            direction = _estimate_direction(block.text_bbox)
        else:
            ppocr_lang = _PPOCR_LANG.get(lang.value, "en")
            text, lines = _run_ppocr(ppocr_lang, crop)
            direction = Direction.HORIZONTAL

        block.original_text = text
        block.texts = lines
        block.lang = lang
        block.direction = direction

    return blocks


def _run_manga_ocr(crop: Image.Image) -> str:
    """manga-ocr: PIL 이미지 → 텍스트 문자열."""
    return registry.ocr_ja(crop)


def _run_ppocr(lang: str, crop: Image.Image) -> tuple[str, list[str]]:
    """PP-OCRv5: numpy 배열 → (joined_text, lines)."""
    import numpy as np
    ocr = registry.ocr_ppocr(lang)
    arr = np.array(crop.convert("RGB"))
    result = ocr.ocr(arr, cls=True)
    if not result or not result[0]:
        return "", []
    lines = [line[1][0] for line in result[0] if line and line[1] and line[1][0]]
    # 중국어/일본어는 공백 없이, 영어는 공백으로 이어붙임
    sep = "" if lang == "ch" else " "
    return sep.join(lines), lines


def _estimate_direction(bbox: tuple[int, int, int, int]) -> Direction:
    """bbox 종횡비로 세로/가로쓰기 추정. 높이 > 너비면 세로."""
    x1, y1, x2, y2 = bbox
    return Direction.VERTICAL if (y2 - y1) > (x2 - x1) else Direction.HORIZONTAL
