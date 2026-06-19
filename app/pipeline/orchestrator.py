"""전체 번역 파이프라인 조율.

감지 → 마스크 → OCR → (읽기순서 정렬) → 인페인팅 → 번역 → 렌더링 순서로
단계를 호출하고, 각 단계가 채운 TextBlock 리스트와 결과 이미지를 응답으로 합친다.
각 단계는 `PipelineOptions`의 해당 하위 옵션을 받는다.
"""
from __future__ import annotations

import time

from app.pipeline import detection, inpainting, ocr, rendering, segmentation, translation
from app.schemas.options import PipelineOptions
from app.schemas.translation import TranslateResponse
from app.utils import image as imageutil


class TranslationPipeline:
    def run(
        self,
        image_bytes: bytes,
        options: PipelineOptions,
        request_id: str,
    ) -> TranslateResponse:
        timing: dict[str, float] = {}
        img = imageutil.load(image_bytes)

        t = time.perf_counter()
        blocks = detection.detect(img, options.detection)              # 1) 감지
        timing["detection"] = _ms(t)

        t = time.perf_counter()
        mask = segmentation.build_mask(img, blocks)                    # 2) 마스크
        timing["segmentation"] = _ms(t)

        t = time.perf_counter()
        blocks = ocr.recognize(img, blocks, options.source_lang, options.ocr)  # 3) OCR
        timing["ocr"] = _ms(t)

        # 읽기 순서 정렬(망가는 우→좌). 번역 문맥과 번역문 매핑 정확도에 중요.
        blocks = _sort_reading_order(blocks, options.render.rtl)

        t = time.perf_counter()
        clean = inpainting.inpaint(img, mask, options.inpaint)         # 4) 인페인팅
        timing["inpaint"] = _ms(t)

        t = time.perf_counter()
        blocks = translation.translate(                                # 5) 번역
            blocks, options.source_lang, options.target_lang, options.translate
        )
        timing["translate"] = _ms(t)

        t = time.perf_counter()
        result = rendering.render(clean, blocks, options.render)       # 6) 식자
        timing["render"] = _ms(t)

        return TranslateResponse(
            request_id=request_id,
            source_lang=options.source_lang,
            target_lang=options.target_lang,
            result_image=imageutil.to_data_url(result),
            blocks=blocks,
            timing_ms=timing,
        )


def _sort_reading_order(blocks: list, right_to_left: bool = True) -> list:
    """블록을 읽기 순서로 정렬 (comic-translate sort_blk_list 참고).

    기본: 위→아래(중심 y), 같은 줄 안에서는 망가 기준 우→좌.
    TODO: 세로쓰기/단(段) 처리 정교화는 Phase 2.
    """
    if not blocks:
        return blocks

    def cx(b):
        return (b.text_bbox[0] + b.text_bbox[2]) / 2

    def cy(b):
        return (b.text_bbox[1] + b.text_bbox[3]) / 2

    return sorted(blocks, key=lambda b: (cy(b), -cx(b) if right_to_left else cx(b)))


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


pipeline = TranslationPipeline()
