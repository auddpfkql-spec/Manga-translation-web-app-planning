"""1) 말풍선·텍스트 감지 — RT-DETR-v2.

모델: ogkalu/comic-text-and-bubble-detector  (comic-translate)
클래스: 0=bubble(말풍선 형태), 1=text_bubble(말풍선 안 글), 2=text_free(말풍선 밖 글)
신뢰도 임계값: opts.confidence (기본 0.3)

웹툰(h/w > 3.5) 슬라이싱은 Phase 2.
"""
from __future__ import annotations

from PIL import Image

from app.models.registry import registry
from app.schemas.options import DetectionOptions
from app.schemas.translation import BlockType, TextBlock

_LABEL_TO_TYPE: dict[int, BlockType] = {
    1: BlockType.TEXT_BUBBLE,
    2: BlockType.TEXT_FREE,
}


def detect(img: Image.Image, opts: DetectionOptions) -> list[TextBlock]:
    """말풍선/텍스트 영역을 검출해 TextBlock 리스트로 반환."""
    import torch  # Colab 환경에서만 사용 가능 — 로컬 임포트
    processor, model, device = registry.detector

    # opts.detection_size 기준으로 긴 변을 제한 (작은 글자 인식률 향상)
    det_img = _maybe_resize(img, opts.detection_size)
    scale_x = img.width / det_img.width
    scale_y = img.height / det_img.height

    inputs = processor(images=det_img, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    target_sizes = torch.tensor([[det_img.height, det_img.width]])
    results = processor.post_process_object_detection(
        outputs, threshold=opts.confidence, target_sizes=target_sizes
    )[0]

    raw_boxes = results["boxes"].cpu().numpy().tolist()
    labels = results["labels"].cpu().numpy().tolist()
    scores = results["scores"].cpu().numpy().tolist()

    bubble_boxes: list[tuple[int, int, int, int]] = []
    text_entries: list[tuple[tuple[int, int, int, int], BlockType, float]] = []

    for box, label, score in zip(raw_boxes, labels, scores):
        x1, y1, x2, y2 = (
            int(box[0] * scale_x), int(box[1] * scale_y),
            int(box[2] * scale_x), int(box[3] * scale_y),
        )
        x1 = max(0, x1);  y1 = max(0, y1)
        x2 = min(img.width, x2);  y2 = min(img.height, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        if label == 0:
            bubble_boxes.append((x1, y1, x2, y2))
        elif label in _LABEL_TO_TYPE:
            text_entries.append(((x1, y1, x2, y2), _LABEL_TO_TYPE[label], float(score)))

    blocks: list[TextBlock] = []
    for idx, (text_bbox, btype, score) in enumerate(text_entries):
        bubble_bbox = _find_containing_bubble(text_bbox, bubble_boxes)
        # 자유 텍스트라도 말풍선이 감싸고 있으면 text_bubble 로 상향
        if bubble_bbox is not None and btype == BlockType.TEXT_FREE:
            btype = BlockType.TEXT_BUBBLE
        blocks.append(TextBlock(
            id=idx,
            text_bbox=text_bbox,
            bubble_bbox=bubble_bbox,
            type=btype,
            score=score,
        ))

    return blocks


def _maybe_resize(img: Image.Image, max_side: int) -> Image.Image:
    """긴 변이 max_side 를 넘으면 비율 유지 리사이즈."""
    if max(img.width, img.height) <= max_side:
        return img
    scale = max_side / max(img.width, img.height)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _find_containing_bubble(
    text_bbox: tuple[int, int, int, int],
    bubble_boxes: list[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    """텍스트 박스 중심점을 포함하는 가장 작은 말풍선 박스를 반환."""
    tx1, ty1, tx2, ty2 = text_bbox
    cx = (tx1 + tx2) / 2
    cy = (ty1 + ty2) / 2

    best: tuple[int, int, int, int] | None = None
    best_area = float("inf")
    for b in bubble_boxes:
        bx1, by1, bx2, by2 = b
        if bx1 <= cx <= bx2 and by1 <= cy <= by2:
            area = (bx2 - bx1) * (by2 - by1)
            if area < best_area:
                best = b
                best_area = area
    return best
