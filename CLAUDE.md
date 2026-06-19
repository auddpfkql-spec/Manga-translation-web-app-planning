# CLAUDE.md — 만화 번역 웹앱 (Manga Translator)

> 이 문서는 **프로젝트 기획서**이자 Claude Code가 작업할 때 따르는 **가이드**입니다.
> 새 작업을 시작하기 전에 항상 이 문서를 먼저 읽고, 변경된 결정은 이 문서에 반영합니다.

---

## 1. 프로젝트 개요

일본어 / 영어 / 중국어 만화(망가·웹툰·코믹스) 이미지를 업로드하면, 말풍선 속 텍스트를
자동으로 **인식 → 제거 → 번역 → 식자**하여 **한국어로 완성된 이미지**를 돌려주는 웹 앱.

- **입력**: 만화 페이지 이미지 (JP / EN / ZH)
- **출력**: 원문이 한국어로 교체된 이미지 + 번역 데이터(JSON)
- **실행 환경**: Google Colab (T4 GPU) + ngrok 터널
- **사용 흐름**: 브라우저에서 이미지 업로드 → 자동 번역 → 결과 미리보기 / 다운로드

### 참고 프로젝트
- [ogkalu2/comic-translate](https://github.com/ogkalu2/comic-translate) — 파이프라인 구성과 모델 선택의 **주 기준** (우리 스택과 동일)
- [zyddnys/manga-image-translator](https://github.com/zyddnys/manga-image-translator) — **서버/웹/API + Colab** 구조의 기준 (§13)
- [dmMaze/BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) — 데스크톱(PyQt), 인페인팅/식자 교차검증

---

## 2. 기술 스택

| 영역 | 기술 | 비고 |
|---|---|---|
| 실행환경 | Google Colab (T4, 16GB VRAM) + ngrok | `pyngrok`로 외부 공개 |
| 백엔드 | FastAPI + Uvicorn | 정적 프론트도 함께 서빙 |
| 말풍선·텍스트 감지 | RT-DETR-v2 (`ogkalu/comic-text-and-bubble-detector`) | comic-translate 모델 |
| OCR (일본어) | manga-ocr (`kha-white/manga-ocr-base`) | 세로/가로쓰기 대응 |
| OCR (영어·중국어) | PaddleOCR **PP-OCRv5** | 다국어 라인 인식 |
| 인페인팅 | **LaMa** (망가 미세조정, IOPaint) | 원문 텍스트 제거 |
| 번역 | **Gemini 2.0 Flash** (`gemini-2.0-flash`) | 페이지 단위 문맥 번역 |
| 프론트엔드 | HTML / CSS / Vanilla JS | 단일 페이지 |

> 모든 비밀키는 `.env` 또는 Colab `userdata`(secrets)로 주입. **절대 커밋 금지.**

---

## 3. 처리 파이프라인

comic-translate 흐름을 기반으로 한 6단계. 각 단계는 `app/pipeline/` 아래 독립 모듈로 구현하고,
`orchestrator.py`가 순서를 조율합니다.

```
            [이미지 업로드]
                  │
                  ▼
   ┌───────────────────────────────┐
   │ 1) 감지  Detection             │  RT-DETR-v2
   │    말풍선 / 자유텍스트 bbox+클래스 │
   └───────────────────────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
   ┌─────────┐         ┌──────────────┐
   │ 2) 마스크 │         │ 3) OCR        │  manga-ocr (JP)
   │  Mask    │         │  언어별 라우팅  │  PP-OCRv5  (EN/ZH)
   └─────────┘         └──────────────┘
        │                    │ 원문 텍스트
        ▼                    ▼
   ┌─────────┐         ┌──────────────┐
   │4) 인페인팅│         │ 5) 번역        │  Gemini 2.0 Flash
   │ Inpaint  │         │  Translate    │  (페이지 문맥 + 블록 원문)
   │ LaMa     │         └──────────────┘
   │ 원문 제거 │                │ 한국어 텍스트
   └─────────┘                 │
        │  깨끗한 배경            │
        └──────────┬───────────┘
                   ▼
            ┌──────────────┐
            │ 6) 렌더링/식자  │  번역문을 말풍선에 배치
            │   Render      │  (폰트 크기 자동, 줄바꿈, 정렬)
            └──────────────┘
                   │
                   ▼
        [결과 이미지 + 번역 JSON]
```

### 단계별 책임
1. **감지 `detection.py`** — RT-DETR-v2로 검출. **3 클래스**(0=말풍선, 1=말풍선 안 텍스트, 2=자유 텍스트)에서 말풍선 박스·텍스트 박스를 분리·연결 → `TextBlock(text_bbox, bubble_bbox, type, score)`
2. **마스크 `segmentation.py`** — 텍스트 영역(폴리곤 우선, 없으면 박스) → 인페인팅용 이진 마스크
3. **OCR `ocr.py`** — 영역 크롭 후 언어 라우팅(일=manga-ocr, 영/중=PP-OCRv5) → 원문 추출
4. **인페인팅 `inpainting.py`** — 마스크 영역을 망가 LaMa로 복원해 원문 제거
5. **번역 `translation.py`** — 블록 원문을 JSON으로 묶어 Gemini에 **페이지 단위**로 전달(문맥 유지) → 한국어 매핑
6. **렌더링 `rendering.py`** — 인페인팅 이미지 위 각 박스에 번역문 식자(폰트 크기/줄바꿈 자동, 가로)

> **데이터 계약**: 각 단계는 `app/schemas/translation.py`의 `TextBlock` 리스트를 입력받아
> 필드를 채워 반환합니다. 단계 추가/교체 시 이 스키마를 기준으로 합니다.
>
> **읽기 순서**: OCR 후 블록을 읽기 순서(망가는 우→좌)로 정렬해야 번역 문맥·매핑이 정확합니다.
> **웹툰(세로 긴 이미지)**: 감지 전 `ImageSlicer`로 분할(h/w>3.5, overlap 0.2) 후 결과를 합칩니다.

---

## 4. 디렉토리 구조

```
.
├── CLAUDE.md                  # 본 기획서 / 작업 가이드
├── README.md                  # 빠른 시작
├── requirements.txt           # Python 의존성
├── .env.example               # 환경변수 템플릿
├── .gitignore
├── notebooks/
│   └── colab_runner.ipynb     # Colab 실행 노트북 (설치→키→서버+ngrok)
├── app/                       # 백엔드 (FastAPI)
│   ├── main.py                # 앱 진입점 / 정적 프론트 서빙
│   ├── config.py              # 설정 (.env 로딩)
│   ├── api/
│   │   └── routes.py          # /api/health, /languages, /translate
│   ├── schemas/
│   │   └── translation.py     # TextBlock, TranslateResponse 등 Pydantic
│   ├── pipeline/
│   │   ├── orchestrator.py    # 전체 파이프라인 조율
│   │   ├── detection.py       # RT-DETR-v2 감지
│   │   ├── segmentation.py    # 텍스트 마스크 생성
│   │   ├── ocr.py             # manga-ocr + PP-OCRv5 라우팅
│   │   ├── inpainting.py      # LaMa 인페인팅
│   │   ├── translation.py     # Gemini 2.0 Flash 번역
│   │   └── rendering.py       # 한국어 식자/렌더링
│   ├── models/
│   │   └── registry.py        # 모델 지연 로딩 + 싱글톤 캐싱
│   └── utils/
│       ├── image.py           # 이미지 변환/크롭/인코딩 유틸
│       └── logging.py         # 로깅 설정
├── frontend/                  # 정적 프론트
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── models/                    # 모델 가중치 (git 제외)
├── fonts/                     # 한국어 폰트 (git 제외)
├── data/
│   ├── input/                 # 업로드 임시
│   └── output/                # 결과 임시
└── tests/
    └── test_pipeline.py
```

---

## 5. API 명세

베이스 경로 `/api`. 프론트는 `/`에서 정적 서빙.

### `GET /api/health`
서버 및 모델 로딩 상태.
```json
{ "status": "ok", "models": { "detector": true, "ocr_ja": false, "inpainter": true } }
```

### `GET /api/languages`
지원 소스 언어 목록.
```json
{ "source": ["auto", "ja", "en", "zh"], "target": ["ko"] }
```

### `GET /api/queue`
현재 대기/처리 상태(단일 GPU 직렬화).
```json
{ "waiting": 0, "busy": false }
```

### `POST /api/translate`
`multipart/form-data`
- `file`: 이미지 (필수)
- `options`: `PipelineOptions` JSON 문자열 (선택, 기본 `{}`) — 예: `{"source_lang":"ja"}`
  - 주요: `source_lang`(auto|ja|en|zh), `target_lang`(ko), 그리고 `detection`/`ocr`/`inpaint`/`translate`/`render` 하위 옵션 (모두 기본값 보유 → `app/schemas/options.py`)

응답:
```json
{
  "request_id": "uuid",
  "source_lang": "ja",
  "target_lang": "ko",
  "result_image": "data:image/png;base64,....",
  "blocks": [
    {
      "id": 0,
      "text_bbox": [x1, y1, x2, y2],
      "bubble_bbox": [x1, y1, x2, y2],
      "type": "text_bubble",
      "direction": "horizontal",
      "original_text": "おはよう",
      "translated_text": "좋은 아침",
      "score": 0.97
    }
  ],
  "timing_ms": { "detection": 120, "ocr": 340, "inpaint": 280, "translate": 600, "render": 40 }
}
```

### (후속) `POST /api/translate/batch`, `POST /api/render`
- batch: 여러 이미지 일괄 처리
- render: 사용자가 `blocks`의 번역문을 수정 후 재식자만 수행

---

## 6. 모델 & VRAM 예산 (T4 16GB)

| 단계 | 모델 / 파일 | 출처 | 백엔드 | VRAM |
|---|---|---|---|---|
| 감지 | RT-DETR-v2 (`RTDetrV2ForObjectDetection`) | `ogkalu/comic-text-and-bubble-detector` | transformers(PyTorch) · INT8 ONNX 대안 | ~1.0GB |
| OCR(일) | manga-ocr | `kha-white/manga-ocr-base` | PyTorch/ONNX | ~0.5GB |
| OCR(영·중) | PP-OCRv5 (`lang='en'`/`'ch'`) | PaddleOCR | ONNX(기본)/PyTorch | ~0.5GB |
| 인페인팅 | `anime-manga-big-lama.pt`(JIT) / `lama-manga-dynamic.onnx` | Sanster·`ogkalu/lama-manga-onnx-dynamic` | TorchScript/ONNX | ~0.5GB |
| 번역 | Gemini 2.0 Flash | Google API | REST/SDK (외부) | 0 |

> 대안 인페인터: AOT(`aot_traced.pt`), MI-GAN(`migan_pipeline_v2.onnx`), SD 인페인팅(고품질·고비용). 망가 LaMa 계열은 세 프로젝트 공통 — manga-image-translator `lama_mpe`(원본) → BallonsTranslator `lama_large_512px.ckpt` → comic-translate `anime-manga-big-lama.pt`.

→ 합산해도 T4 한도 내. 모든 모델은 **지연 로딩 + 싱글톤**(`app/models/registry.py`)으로 1회만 로드.
첫 요청 콜드스타트가 길므로, 선택적 startup warmup 옵션을 둠.

---

## 7. 개발 로드맵

- **Phase 0 — 환경 구축** ✅ *(서버 골격 완료)*: FastAPI 서버 + `/health`·`/languages`·`/queue` + 정적 프론트 서빙 + **요청 큐(단일 GPU 직렬화)** + 통합 `PipelineOptions`. 스모크 테스트 `tests/test_server.py`. (Colab 노트북·ngrok은 작성됨)
- **Phase 1 — 파이프라인 골격** *(진행 중)*: ✅ **마스크·식자·번역 로직 + 인페인팅 `none`** 구현. 오케스트레이터 **end-to-end 검증**(GPU/네트워크 가짜 대체, `tests/test_stages.py`·`tests/test_integration.py`) · ⬜ **감지·OCR·LaMa 인페인팅**은 Colab/GPU 필요 — `registry.py` 채우기
- **Phase 2 — 품질**: 언어 자동감지, 세로쓰기 **읽기순서**, 웹툰 슬라이싱, **번역 후 검증/재시도**, 마스크 정제, 식자 품질, 색상/외곽선 추정
- **Phase 3 — UX**: **진행률 스트리밍(큐 위치→단계별)**, 원문/번역 미리보기, **수동 편집 후 재렌더**, 배치 처리
- **Phase 4 — 최적화**: 모델 로딩 단축, GPU 메모리 관리, 에러 핸들링, 결과 캐시

---

## 8. Colab + ngrok 실행 (요약)

`notebooks/colab_runner.ipynb` 참조. 핵심 순서:
1. 런타임 → GPU(T4) 선택
2. 레포 클론 + `pip install -r requirements.txt`
3. **⚠️ CUDA torch 복구**: deps가 torch를 CPU판으로 다운그레이드할 수 있어 cu124 빌드로 강제 재설치 → `torch.cuda.is_available()` 확인
4. `userdata`에서 `GEMINI_API_KEY`, `NGROK_AUTHTOKEN` 로드 → 환경변수 주입
5. `uvicorn app.main:app` 백그라운드 실행 + `pyngrok`로 공개 URL 생성
   - (대안) ngrok 없이 `google.colab.kernel.proxyPort(8000)` 로 공개 — 토큰 불필요
6. 출력된 URL 접속

---

## 9. 개발 규칙 (Claude 작업 지침)

- **소통은 한국어**로 한다.
- **비밀키 절대 커밋 금지**. `.env`는 git 제외, Colab에서는 `google.colab.userdata` 사용.
- **대용량/모델 가중치 커밋 금지** (`models/`, 폰트는 `.gitignore`).
- 모델은 **지연 로딩 + 싱글톤**. 직접 `from_pretrained` 호출하지 말고 `registry.py`를 거친다.
- 파이프라인 단계는 **입출력 인터페이스(`TextBlock`) 고정**, 단독 테스트 가능하게 유지.
- 무거운 추론(동기·CPU/GPU bound)은 FastAPI에서 `run_in_threadpool`로 감싸고, **단일 GPU 직렬화**(`asyncio.Semaphore(1)`)로 동시 1건만 처리.
- 의존성은 `requirements.txt`에 명시. **torch는 requirements에 넣지 않음** — Colab CUDA 빌드 사용. 단, OCR/인페인팅 설치가 torch를 CPU판으로 다운그레이드하면 cu124로 **강제 재설치** 후 CUDA 확인.
- **커밋·푸시는 사용자가 명시적으로 요청할 때만** 수행한다.

---

## 10. 가정 및 결정사항

- 1차 목표는 **단일 이미지 자동 번역**. 배치/수동편집은 Phase 3.
- 한국어 폰트는 무료 라이선스(예: Pretendard, 나눔 계열)를 `fonts/`에 배치하고 라이선스를 확인한다.
- 결과는 Colab 세션 임시(`data/output`). 영구 저장(Drive 연동)은 후속.
- 소스 언어는 기본 `auto`(감지) + 사용자 수동 선택 허용.

---

## 11. 결정사항 (참고 프로젝트 분석으로 해소)

- **세로쓰기 식자**: 불필요. 대상이 한국어(가로쓰기)라 출력은 항상 가로. 소스의 세로쓰기(`direction=vertical`)는 OCR 읽기 순서에만 사용. (comic-translate `render.py` 근거)
- **웹툰 분할**: 필요. 감지 전 `ImageSlicer`로 분할(h/w>3.5, overlap 0.2) 후 합침. (comic-translate `webtoon_batch` 근거)
- **기본 인페인터**: 망가 LaMa(`anime-manga-big-lama.pt` JIT 또는 ONNX). 두 참고 프로젝트 공통.
- **OCR 백엔드**: ONNX 기본(경량·고속), 옵션 PyTorch.

### 남은 확정 항목
- 수동 편집 UI 범위 — 텍스트 수정만(권장) vs 위치/폰트까지 (Phase 3)
- 한국어 식자 폰트 최종 선택 (예: Pretendard / 나눔손글씨)

---

## 12. 참고 프로젝트에서 차용한 설계 (검증됨)

> comic-translate(ogkalu2) 코드를 직접 분석해 우리 스택과 1:1로 대응하는 설계를 확정.
> BallonsTranslator는 인페인팅/식자 교차검증에 사용.

### 12.1 아키텍처 패턴 — 엔진 교체 가능 구조
comic-translate는 각 단계를 **`base.py`(엔진 인터페이스) + `factory.py`(엔진 선택) + `processor`/`handler`(조율)** 로 구성해 백엔드를 쉽게 교체한다(LaMa↔AOT↔MI-GAN, manga-ocr↔PP-OCR, Gemini↔GPT↔Claude).
→ 우리는 1차에선 단순 함수형 `pipeline/`을 쓰되, **두 번째 백엔드가 필요해지면 단계별 `base`+`factory`로 승격**한다. `registry.py`가 그 자리를 미리 잡아둠.

### 12.2 번역 계약 (가장 중요)
- 페이지 전체 블록을 **한 번의 호출**로 번역(문맥/화자 일관성).
- 직렬화: `{"block_0": "원문", "block_1": "..."}` (키는 번역 금지).
- 응답 파싱: 정규식 `\{[\s\S]*\}` 로 JSON만 추출 후 `block_{i}` 매핑 (LLM이 군말을 붙여도 견고).
- `safety_settings` 전부 **BLOCK_NONE** (만화 콘텐츠가 안전필터에 막혀 번역이 비는 것 방지).
- system_instruction은 **한국어 출력에 맞춰 튜닝**("당신/그녀/그" 회피) — `app/pipeline/translation.py:SYSTEM_PROMPT`.
- (선택) 페이지 이미지를 base64로 동봉하면 문맥 품질↑.

### 12.3 감지 출력
- 3 클래스: `0=bubble`, `1=text_bubble`, `2=text_free`. 신뢰도 임계값 0.3.
- 말풍선 박스·텍스트 박스를 분리하고, 텍스트를 감싼 말풍선을 찾아 연결 → 식자 기준 박스로 사용.

### 12.4 데이터 구조 (TextBlock)
텍스트 박스/말풍선 박스 분리, 세그 폴리곤(정밀 마스크), `direction`, `angle`, 줄별 텍스트, 식자 힌트(폰트색·min/max 크기·정렬·줄간격)를 한 객체에 담아 단계 간 전달 → `app/schemas/translation.py`에 반영.

### 12.5 식자 (rendering)
PIL 래스터. 기준 박스를 약간 shrink → min~max 폰트 크기에서 들어맞을 때까지 탐색 → 그리디 줄바꿈(한국어=공백 단위) → 외곽선(stroke)으로 가독성. 한국어는 가로 고정.

### 참고 레포 (로컬 분석본)
얕은 클론을 임시 폴더(`%TEMP%\manga-ref\`)에 받아 분석. 재현:
`git clone --depth 1 https://github.com/ogkalu2/comic-translate` · `.../dmMaze/BallonsTranslator` · `.../zyddnys/manga-image-translator`

---

## 13. manga-image-translator 분석 (웹서비스 설계 보강)

> zyddnys/manga-image-translator — **서버/웹/API 모드 + Colab 런처**를 갖춰 우리 배포 형태(Colab+웹)와 가장 유사. FastAPI 기반.

### 13.1 서버 아키텍처 (직접 반영)
- **FastAPI** + 요청마다 **통합 `Config`(JSON)** 로 파이프라인 전체 제어(검출/OCR/인페인팅/번역/렌더 옵션). → **반영됨**: `app/schemas/options.py:PipelineOptions` (multipart `options` 필드).
- **요청 큐 = 단일 처리**: 단일 GPU라 한 번에 1건만, 큐 위치를 클라이언트에 보고. → 우리는 `asyncio.Semaphore(1)` + `/api/queue` 로 단순화 (반영됨: `app/api/routes.py`).
- **진행률 스트리밍**(StreamingResponse): 상태코드(0=결과, 1=진행, 2=에러, 3=큐위치, 4=대기)로 단계별 진행 전송. → Phase 3 UX.
- **폼 업로드**(`/translate/with-form/image`) + json/bytes/image 다중 출력. 결과를 `result/{id}/final.png`로 저장·정적 서빙.

### 13.2 파이프라인 추가 단계
- **mask_refinement**: 검출 박스 → 실제 글자 픽셀로 **마스크 정제** 후 인페인팅(`text_mask_utils.py`). 우리 `segmentation.py`를 박스→정제로 강화.
- **textline_merge**(줄→블록 병합), **panel_finder**(컷 단위 읽기순서).

### 13.3 번역 품질 (Phase 2 반영)
- **번역 후 검증/재시도**: 반복(환각) 감지(동일 구 20회+), **타겟 언어 비율<0.5면 실패**, 결과 수≠블록 수면 재시도(최대 3회). (`app/pipeline/translation.py` 가이드 추가)
- **2-stage 번역**(`gemini_2stage`): 1차 번역 → 2차 교정. 품질 옵션.
- **skip_lang / translator chain**: 이미 타겟 언어면 건너뜀.

### 13.4 검출·렌더 파라미터 (수치 기준)
- 검출: `detection_size=2048`, `box_threshold=0.7`, `unclip_ratio=2.3`(스켈레톤→박스 확장). (선택) **검출 전 업스케일**로 작은 글자 인식률↑.
- 렌더: **최소 폰트 = (가로+세로)/200**, 줄간격 가로 0.01, **rtl=True**(컷·블록 우→좌), 폰트색 `fg:bg` hex 지정/추정.

### 13.5 인페인팅 계보
`lama_mpe`(원본) → BallonsTranslator 차용 → comic-translate `anime-manga-big-lama`. 추가로 **SD 인페인팅**(고품질·고비용) 옵션 존재. 우리 기본은 망가 LaMa 유지.

### 13.6 Colab 실행 교정 (중요)
- `pip install` 후 manga-ocr/paddleocr가 **torch를 CPU판으로 다운그레이드**할 수 있음 → CUDA torch **강제 재설치** 후 `torch.cuda.is_available()` 확인. (노트북 3·4번 셀 반영)
- ngrok 없이 **`google.colab.kernel.proxyPort(8000)`** 로 공개 URL 가능(토큰 불필요, 노트북 6-B).
