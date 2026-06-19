"""Phase 1 — 모델 불필요 단계 테스트 (마스크/식자/번역 로직).

GPU·네트워크 없이 검증 가능한 부분만 다룬다.
- segmentation.build_mask : 순수 PIL
- rendering.render        : 순수 PIL (폰트)
- translation 순수 로직    : JSON 직렬화/파싱, 검증/재시도 판정 (네트워크 호출 _call_gemini 는 제외)
"""
from __future__ import annotations

from PIL import Image

from app.pipeline import rendering, segmentation, translation
from app.schemas.options import RenderOptions
from app.schemas.translation import TextBlock


def _img(w, h, color=(255, 255, 255)):
    return Image.new("RGB", (w, h), color)


# ── segmentation ──────────────────────────────────────────────
def test_build_mask_box():
    mask = segmentation.build_mask(_img(40, 40), [TextBlock(id=0, text_bbox=(10, 10, 20, 20))], dilate=0)
    assert mask.size == (40, 40)
    assert mask.getpixel((15, 15)) == 255   # 박스 안 = 흰색
    assert mask.getpixel((2, 2)) == 0       # 박스 밖 = 검정


def test_build_mask_empty():
    mask = segmentation.build_mask(_img(20, 20), [], dilate=0)
    assert mask.getpixel((10, 10)) == 0


def test_build_mask_polygon():
    blk = TextBlock(id=0, text_bbox=(0, 0, 1, 1), segm_points=[(5, 5), (25, 5), (25, 25), (5, 25)])
    mask = segmentation.build_mask(_img(30, 30), [blk], dilate=0)
    assert mask.getpixel((15, 15)) == 255


# ── rendering ─────────────────────────────────────────────────
def test_render_draws_text():
    base = _img(200, 100)
    blk = TextBlock(id=0, text_bbox=(20, 20, 180, 80), translated_text="Hello")  # 폰트 무관하게 그려지는 라틴문자
    out = rendering.render(base, [blk], RenderOptions())
    assert out.size == (200, 100)
    assert out.tobytes() != _img(200, 100).tobytes()   # 무언가 그려졌다


def test_render_skips_empty_translation():
    out = rendering.render(_img(50, 50), [TextBlock(id=0, text_bbox=(5, 5, 45, 45))], RenderOptions())
    assert out.tobytes() == _img(50, 50).tobytes()      # 번역문 없으면 그대로


# ── translation (순수 로직) ───────────────────────────────────
def test_translation_json_roundtrip_robust_parse():
    blks = [
        TextBlock(id=0, text_bbox=(0, 0, 1, 1), original_text="こんにちは"),
        TextBlock(id=1, text_bbox=(0, 0, 1, 1), original_text="ありがとう"),
    ]
    translation._to_json(blks)
    # LLM 이 앞뒤로 군말을 붙여도 {...} 만 추출되어야 함
    resp = '네 결과입니다 {"block_0": "안녕하세요", "block_1": "감사합니다"} 이상입니다'
    translation._apply_json(blks, resp)
    assert blks[0].translated_text == "안녕하세요"
    assert blks[1].translated_text == "감사합니다"


def test_korean_ratio():
    assert translation._korean_ratio("안녕") == 1.0
    assert translation._korean_ratio("abc") == 0.0


def test_validate_pass_and_fail():
    ok_blocks = [TextBlock(id=0, text_bbox=(0, 0, 1, 1), original_text="x", translated_text="안녕하세요")]
    ok, _ = translation._validate(ok_blocks, "ko")
    assert ok

    # 반복(환각) + 비한국어 → 실패
    bad = [TextBlock(id=0, text_bbox=(0, 0, 1, 1), original_text="x", translated_text="a" * 30)]
    ok, reason = translation._validate(bad, "ko")
    assert not ok
