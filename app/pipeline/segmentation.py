"""2) 인페인팅용 텍스트 마스크 생성.

감지 단계에서 segm_points(폴리곤)가 있으면 그것으로 정밀 마스크를,
없으면 text_bbox 사각형으로 마스크를 만든다. dilation 으로 글자 외곽까지 덮는다.
모델이 필요 없는 순수 CV 단계.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from app.schemas.translation import TextBlock


def build_mask(img: Image.Image, blocks: list[TextBlock], dilate: int = 2) -> Image.Image:
    """텍스트 영역(blocks)으로부터 원문 픽셀 이진 마스크(0/255, 'L')를 만든다.

    - segm_points 있으면 polygon, 없으면 text_bbox 사각형을 흰색(255)으로 채움
    - dilate>0 이면 MaxFilter 로 마스크를 살짝 팽창(글자 안티앨리어싱 가장자리 포함)
    - (Phase 2) bbox 내부에서 실제 글자 픽셀만 남기는 정밀 정제 추가 예정
    """
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)

    for b in blocks:
        if b.segm_points:
            draw.polygon([tuple(p) for p in b.segm_points], fill=255)
        else:
            draw.rectangle(list(b.text_bbox), fill=255)

    if dilate > 0:
        mask = mask.filter(ImageFilter.MaxFilter(dilate * 2 + 1))

    return mask
