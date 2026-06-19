# 만화 번역 웹앱 (Manga Translator)

일본어 / 영어 / 중국어 만화 이미지를 업로드하면 **한국어로 자동 번역·식자**하여 돌려주는 웹 앱.
Google Colab(T4) + ngrok 환경에서 동작합니다.

> 📄 전체 기획·아키텍처·작업 규칙은 **[CLAUDE.md](CLAUDE.md)** 참조.

## 파이프라인
`감지(RT-DETR-v2)` → `마스크` → `OCR(manga-ocr / PP-OCRv5)` → `인페인팅(LaMa)` → `번역(Gemini 2.0 Flash)` → `식자`

## 빠른 시작 (로컬)
```bash
pip install -r requirements.txt
cp .env.example .env          # 키 채우기 (GEMINI_API_KEY 등)
uvicorn app.main:app --reload
# 브라우저에서 http://localhost:8000
```

## 서버 골격 스모크 테스트 (모델 불필요)
모델 추론 없이 라우트·큐·옵션·정적 프론트 서빙만 검증 — 경량 deps만 있으면 됩니다.
```bash
pip install fastapi pydantic pydantic-settings pillow loguru httpx python-multipart pytest
python -m pytest -q
```

## Colab에서 실행
`notebooks/colab_runner.ipynb` 를 Colab에서 열고 위에서부터 실행하면
ngrok 공개 URL이 출력됩니다. (런타임 → GPU(T4) 선택 필수)

## 프로젝트 구조
```
app/         FastAPI 백엔드 (api / pipeline / models / schemas / utils)
frontend/    HTML·CSS·JS 정적 프론트
notebooks/   Colab 실행 노트북
models/      모델 가중치 (git 제외)
fonts/       한국어 폰트 (git 제외)
data/        입출력 임시
tests/       테스트
```

## 환경변수
| 키 | 설명 |
|---|---|
| `GEMINI_API_KEY` | Gemini 2.0 Flash API 키 |
| `NGROK_AUTHTOKEN` | ngrok 토큰 (Colab 공개용) |
| `TARGET_LANG` | 대상 언어 (기본 `ko`) |

자세한 항목은 `.env.example` 참조.

## 참고
- [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)
- [comic-translate](https://github.com/ogkalu2/comic-translate)
