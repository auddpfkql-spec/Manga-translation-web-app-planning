"""6) 렌더링/식자 — 번역된 한국어 텍스트를 말풍선 영역에 배치.

comic-translate/modules/rendering 의 래스터 식자 방식을 PIL 로 구현:
  - 기준 박스(bubble_bbox 우선, 없으면 text_bbox)를 약간 shrink
  - 폰트 크기를 max→min 으로 낮추며 줄바꿈 후 박스에 맞는 최대 크기 선택
  - 최소 폰트 = (가로+세로)/200 (manga-image-translator 기준) + font_size_offset
  - 그리디 줄바꿈(한국어=공백 단위), 가운데 정렬, 외곽선(stroke)로 가독성
  - 대상이 한국어이므로 항상 가로쓰기
모델이 필요 없는 순수 PIL 단계. (한국어 폰트는 fonts/ 또는 시스템 폰트에서 로드)
"""
from __future__ import annotations

import glob

from PIL import Image, ImageDraw, ImageFont

from app.schemas.options import RenderOptions
from app.schemas.translation import TextBlock

_FONT_CACHE: dict[tuple[int, str], ImageFont.ImageFont] = {}


def _load_font(size: int, family: str | None) -> ImageFont.ImageFont:
    """TrueType 폰트를 (지정 → fonts/ → 시스템 한국어 폰트) 순으로 시도, 실패 시 기본 폰트."""
    key = (size, family or "")
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    candidates: list[str] = []
    if family:
        candidates.append(family)
    # 번들 폰트(fonts/) 우선 — Colab에서도 여기에 받아두면 잡힌다.
    candidates += sorted(glob.glob("fonts/*.ttf")) + sorted(glob.glob("fonts/*.otf"))
    # 시스템 한국어 폰트 (윈도우 + 리눅스/Colab 경로 모두 시도)
    candidates += [
        "malgun.ttf", "C:/Windows/Fonts/malgun.ttf",                    # Windows
        "NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",             # apt fonts-nanum
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # apt fonts-noto-cjk
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]

    font: ImageFont.ImageFont | None = None
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None:
        # 한글 글리프가 없는 기본 폰트로 떨어지면 결과가 □(두부)가 된다.
        # fonts/ 에 한국어 TTF 를 두거나 Colab 에서 fonts-nanum 설치를 권장.
        font = ImageFont.load_default()

    _FONT_CACHE[key] = font
    return font


def _wrap(text: str, font, draw: ImageDraw.ImageDraw, max_w: float) -> str:
    """공백 단위 그리디 줄바꿈. 한 단어가 너무 길면 그대로 한 줄로 둔다."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        cur = ""
        for word in paragraph.split():
            cand = word if not cur else f"{cur} {word}"
            if draw.textlength(cand, font=font) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return "\n".join(lines)


def _fit(draw, text, box_w, box_h, family, max_size, min_size, spacing_ratio):
    """박스에 들어가는 가장 큰 폰트 크기를 찾는다 (max→min 탐색)."""
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, family)
        wrapped = _wrap(text, font, draw, box_w)
        spacing = max(0, int(size * spacing_ratio))
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=spacing, align="center")
        if (bbox[2] - bbox[0]) <= box_w and (bbox[3] - bbox[1]) <= box_h:
            return font, wrapped, spacing
    font = _load_font(min_size, family)
    return font, _wrap(text, font, draw, box_w), max(0, int(min_size * spacing_ratio))


def render(clean_img: Image.Image, blocks: list[TextBlock], opts: RenderOptions) -> Image.Image:
    """인페인팅된 이미지 위 각 블록에 번역문을 그린다. 원본과 동일 크기 반환."""
    img = clean_img.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base_min = max(8, (opts.min_font_size or (w + h) // 200) + opts.font_size_offset)

    for b in blocks:
        text = (b.translated_text or "").strip()
        if not text:
            continue

        x1, y1, x2, y2 = b.bubble_bbox or b.text_bbox
        bw, bh = max(1, x2 - x1), max(1, y2 - y1)
        pad = max(2, int(min(bw, bh) * 0.08))
        box_w, box_h = max(1, bw - 2 * pad), max(1, bh - 2 * pad)
        max_size = min(80, max(base_min, box_h))

        font, wrapped, spacing = _fit(
            draw, text, box_w, box_h, opts.font_family, max_size, base_min, 0.01
        )

        draw.multiline_text(
            (x1 + bw / 2, y1 + bh / 2),
            wrapped,
            font=font,
            fill=b.font_color or (0, 0, 0),
            anchor="mm",
            align=opts.alignment if opts.alignment in ("left", "center", "right") else "center",
            spacing=spacing,
            stroke_width=2 if opts.outline else 0,
            stroke_fill=(255, 255, 255),
        )

    return img
