"""Phase 0 — 서버 골격 스모크 테스트.

모델 추론 없이(라우트/큐/옵션/정적 프론트 서빙) 서버가 맞물려 뜨는지 검증한다.
무거운 ML 추론 경로(/api/translate)는 Phase 1 에서 구현되므로 여기선 건드리지 않는다.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "detector" in body["models"]


def test_languages():
    r = client.get("/api/languages")
    assert r.status_code == 200
    body = r.json()
    assert "ja" in body["source"] and "en" in body["source"] and "zh" in body["source"]
    assert body["target"] == ["ko"]


def test_queue_idle():
    r = client.get("/api/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["waiting"] == 0
    assert body["busy"] is False


def test_frontend_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "만화 번역기" in r.text


def test_translate_reports_failing_stage():
    """요청이 전 경로(업로드·옵션·큐·오케스트레이터)를 거쳐 감지 단계까지 도달하고,
    실패 시 **어느 단계에서 실패했는지**가 응답 본문에 담기는지 검증.
    (로컬엔 torch 가 없어 detection 에서 모델 로드 실패 → stage='detection')"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, format="PNG")

    no_raise = TestClient(app, raise_server_exceptions=False)
    r = no_raise.post(
        "/api/translate",
        files={"file": ("t.png", buf.getvalue(), "image/png")},
        data={"options": '{"source_lang":"ja"}'},
    )
    assert r.status_code == 500
    body = r.json()
    assert body["error"] == "pipeline_stage_failed"
    assert body["stage"] == "detection"      # 실패 구간이 명시됨
    assert "detail" in body                  # 원인 메시지 포함
