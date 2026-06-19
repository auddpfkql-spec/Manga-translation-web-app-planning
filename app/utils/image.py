"""이미지 입출력/변환 유틸 (PIL 기반)."""
from __future__ import annotations

import base64
import io

from PIL import Image


def load(image_bytes: bytes) -> Image.Image:
    """업로드 바이트 → RGB PIL 이미지."""
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def crop(img: Image.Image, bbox: tuple[int, int, int, int]) -> Image.Image:
    """bbox(x1, y1, x2, y2) 영역 크롭."""
    return img.crop(bbox)


def to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    """PIL 이미지 → base64 data URL (프론트로 그대로 전송 가능)."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/{fmt.lower()};base64,{b64}"
