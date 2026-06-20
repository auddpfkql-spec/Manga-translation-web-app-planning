"""전체 번역 파이프라인 조율.

감지 → 마스크 → OCR → (읽기순서 정렬) → 인페인팅 → 번역 → 렌더링 순서로
단계를 호출하고, 각 단계가 채운 TextBlock 리스트와 결과 이미지를 응답으로 합친다.
각 단계는 `PipelineOptions`의 해당 하위 옵션을 받는다.

진단: 각 단계의 시작/완료를 로그로 남기고, 어떤 단계에서 예외가 나면
`PipelineStageError(stage=...)` 로 감싸 **어느 구간에서 실패했는지** 분명히 한다.
(API 는 이 stage 를 응답 본문에 담아 돌려준다 → 노트북에서 바로 확인 가능)
"""
from __future__ import annotations

import time

from loguru import logger

from app.pipeline import detection, inpainting, ocr, rendering, segmentation, translation
from app.schemas.options import PipelineOptions
from app.schemas.translation import TranslateResponse
from app.utils import image as imageutil

# 전체 단계 수 (로그 [i/N] 표기용)
_TOTAL_STAGES = 6


class PipelineStageError(Exception):
    """파이프라인 특정 단계에서 발생한 실패. stage 로 구간을 식별한다."""

    def __init__(self, stage: str, original: Exception):
        self.stage = stage
        self.original = original
        super().__init__(f"[{stage}] 단계 실패: {type(original).__name__}: {original}")


class TranslationPipeline:
    def run(
        self,
        image_bytes: bytes,
        options: PipelineOptions,
        request_id: str,
    ) -> TranslateResponse:
        timing: dict[str, float] = {}
        logger.info(f"━━━ 파이프라인 시작 (request_id={request_id}) ━━━")

        # 0) 이미지 로드 (단계 번호 없음 — 전처리)
        img = self._stage("load", "이미지 로드", 0, timing,
                          lambda: imageutil.load(image_bytes))
        logger.info(f"    이미지 크기: {img.size[0]}x{img.size[1]}")

        # 1) 감지
        blocks = self._stage("detection", "감지(RT-DETR)", 1, timing,
                            lambda: detection.detect(img, options.detection))
        logger.info(f"    감지된 블록: {len(blocks)}개")

        # 2) 마스크
        mask = self._stage("segmentation", "마스크 생성", 2, timing,
                          lambda: segmentation.build_mask(img, blocks))

        # 3) OCR
        blocks = self._stage("ocr", "OCR", 3, timing,
                           lambda: ocr.recognize(img, blocks, options.source_lang, options.ocr))

        # 읽기 순서 정렬 (망가는 우→좌)
        blocks = _sort_reading_order(blocks, options.render.rtl)

        # 4) 인페인팅
        clean = self._stage("inpaint", "인페인팅", 4, timing,
                          lambda: inpainting.inpaint(img, mask, options.inpaint))

        # 5) 번역
        blocks = self._stage("translate", "번역(Gemini)", 5, timing,
                           lambda: translation.translate(
                               blocks, options.source_lang, options.target_lang, options.translate))

        # 6) 식자
        result = self._stage("render", "렌더링/식자", 6, timing,
                           lambda: rendering.render(clean, blocks, options.render))

        logger.info(f"━━━ 파이프라인 완료 (총 {sum(timing.values()):.0f}ms) ━━━")
        return TranslateResponse(
            request_id=request_id,
            source_lang=options.source_lang,
            target_lang=options.target_lang,
            result_image=imageutil.to_data_url(result),
            blocks=blocks,
            timing_ms=timing,
        )

    def _stage(self, name: str, label: str, idx: int, timing: dict, fn):
        """한 단계를 실행하며 시작/완료를 로그로 남기고, 실패 시 단계명을 붙여 재발생."""
        marker = f"[{idx}/{_TOTAL_STAGES}]" if idx else "[전처리]"
        logger.info(f"{marker} {label} 시작…")
        t = time.perf_counter()
        try:
            result = fn()
        except Exception as e:
            ms = _ms(t)
            logger.error(f"{marker} {label} 실패 ({ms}ms): {type(e).__name__}: {e}")
            raise PipelineStageError(name, e) from e
        ms = _ms(t)
        if idx:
            timing[name] = ms
        logger.info(f"{marker} {label} 완료 ({ms}ms)")
        return result


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
