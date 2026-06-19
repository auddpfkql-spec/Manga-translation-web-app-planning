"""5) 번역 — Gemini 2.0 Flash. 페이지 단위 문맥 번역.

comic-translate + manga-image-translator 의 검증된 방식을 차용:
  - 블록 전체를 JSON 한 번에 번역(문맥/화자 일관성):  {"block_0": "...", ...}
  - 응답에서 정규식으로 {...} 만 추출해 파싱(견고)
  - safety_settings 전부 BLOCK_NONE (만화 콘텐츠가 필터에 막혀 거부되는 것 방지)
  - 번역 후 검증(반복/한국어 비율/누락) 실패 시 재시도

순수 로직(_to_json/_apply_json/_validate)은 모델 없이 테스트 가능.
실제 Gemini 호출(_call_gemini)만 API 키/네트워크가 필요하다.
"""
from __future__ import annotations

import json
import re

from app.config import settings
from app.schemas.options import TranslateOptions
from app.schemas.translation import SourceLang, TextBlock

SYSTEM_PROMPT = (
    "You are an expert translator who translates {src} to Korean. "
    "Pay attention to style, formality, idioms, and slang, and convey it the way a "
    "Korean speaker would. BE NATURAL. NEVER USE 당신, 그녀, 그 or their Japanese equivalents. "
    "You are translating text OCR'd from a comic; the OCR may contain typos. "
    "You are given a JSON of detected text blocks. Return the JSON with values translated. "
    "DO NOT translate the keys. If a value is already Korean or looks like gibberish, output it as-is. "
    "DO NOT add explanations."
)


def _to_json(blocks: list[TextBlock]) -> str:
    """블록 → {"block_0": 원문, ...} JSON (comic-translate get_raw_text 방식)."""
    return json.dumps(
        {f"block_{i}": (b.original_text or "") for i, b in enumerate(blocks)},
        ensure_ascii=False,
    )


def _apply_json(blocks: list[TextBlock], response_text: str) -> None:
    """LLM 응답에서 {...} 추출 → block_{i} 매핑 (set_texts_from_json 방식)."""
    match = re.search(r"\{[\s\S]*\}", response_text)
    if not match:
        return
    data = json.loads(match.group(0))
    for i, b in enumerate(blocks):
        if f"block_{i}" in data:
            b.translated_text = data[f"block_{i}"]


def _korean_ratio(text: str) -> float:
    """공백 제외 문자 중 한글 음절 비율."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 1.0
    ko = sum(1 for c in letters if "가" <= c <= "힣")
    return ko / len(letters)


def _has_repetition(text: str, threshold: int = 20) -> bool:
    """같은 문자가 threshold 회 이상 연속되면 환각 의심."""
    run = 1
    for i in range(1, len(text)):
        if text[i] == text[i - 1]:
            run += 1
            if run >= threshold:
                return True
        else:
            run = 1
    return False


def _validate(
    blocks: list[TextBlock],
    target_lang: str,
    lang_ratio: float = 0.5,
    repetition_threshold: int = 20,
) -> tuple[bool, str]:
    """번역 후 검증 (manga-image-translator 차용). (ok, reason) 반환."""
    for b in blocks:
        if (b.original_text or "").strip() and not (b.translated_text or "").strip():
            return False, "missing translation"
        if _has_repetition(b.translated_text or "", repetition_threshold):
            return False, "repetition (hallucination)"
    if target_lang == "ko":
        joined = "".join(b.translated_text or "" for b in blocks)
        if joined and _korean_ratio(joined) < lang_ratio:
            return False, "low korean ratio"
    return True, "ok"


def _call_gemini(system_prompt: str, user_prompt: str, opts: TranslateOptions, image=None) -> str:
    """격리된 Gemini 호출 (API 키/SDK 필요 — 테스트에서는 호출하지 않음)."""
    import google.generativeai as genai

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않았습니다.")

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        opts.model,
        system_instruction=system_prompt,
        safety_settings={
            "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
            "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
            "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
        },
    )
    parts = [image, user_prompt] if (opts.use_image_context and image is not None) else [user_prompt]
    return model.generate_content(parts).text


def translate(
    blocks: list[TextBlock],
    source_lang: SourceLang,
    target_lang: str,
    opts: TranslateOptions,
) -> list[TextBlock]:
    """블록 원문을 모아 한 번에 target_lang(기본 한국어)으로 번역 후 각 블록에 매핑.

    검증 실패 시 opts.max_retries 까지 재시도. 원문이 모두 비면 호출 생략.
    (페이지 이미지 동봉(opts.use_image_context)은 orchestrator 가 image 를 전달해야 하므로
     Phase 2 에서 배선 — 현재는 텍스트만 전송)
    """
    if not any((b.original_text or "").strip() for b in blocks):
        return blocks

    system_prompt = SYSTEM_PROMPT.format(src=source_lang.value)
    user_prompt = f"Translate the values of this JSON to {target_lang}:\n{_to_json(blocks)}"

    for _ in range(max(1, opts.max_retries)):
        response = _call_gemini(system_prompt, user_prompt, opts)
        _apply_json(blocks, response)
        ok, _reason = _validate(blocks, target_lang)
        if ok:
            break
    return blocks
