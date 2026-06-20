"""모델 지연 로딩 + 싱글톤 캐싱.

각 모델은 첫 접근 시 1회만 로드된다. 파이프라인은 반드시 이 레지스트리를 통해
모델에 접근한다(직접 from_pretrained 금지). T4 VRAM 예산은 CLAUDE.md §6 참조.

확정된 모델 (참고 프로젝트 분석):
  detector  : ogkalu/comic-text-and-bubble-detector
              transformers RTDetrV2ForObjectDetection (PyTorch)
  ocr_ja    : kha-white/manga-ocr-base                 (manga-ocr)
  ocr_ppocr : PaddleOCR PP-OCRv5, lang 별 ('en' / 'ch') / use_angle_cls=True
  inpainter : anime-manga-big-lama.pt (JIT)  또는  lama-manga-dynamic.onnx
번역(Gemini)은 API 호출이라 여기서 로드하지 않는다.
"""
from __future__ import annotations

from functools import cached_property
from pathlib import Path


class ModelRegistry:
    @cached_property
    def detector(self):
        """RT-DETR-v2 (ogkalu/comic-text-and-bubble-detector).

        반환: (processor, model, device) 튜플.
        processor 는 이미지 전처리·후처리 담당.
        """
        import torch
        from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection

        repo = "ogkalu/comic-text-and-bubble-detector"
        device = "cuda" if torch.cuda.is_available() else "cpu"
        processor = RTDetrImageProcessor.from_pretrained(repo)
        model = RTDetrV2ForObjectDetection.from_pretrained(repo).to(device).eval()
        return processor, model, device

    @cached_property
    def ocr_ja(self):
        """manga-ocr (kha-white/manga-ocr-base). 세로/가로 일본어 모두 처리."""
        from manga_ocr import MangaOcr
        return MangaOcr()

    def ocr_ppocr(self, lang: str):
        """PaddleOCR PP-OCRv5 (lang='en'|'ch'). 언어별 인스턴스를 캐싱.

        PaddleOCR 2.x / 3.x 의 생성자 인자가 다르다(3.x는 use_angle_cls·show_log 제거,
        use_textline_orientation 사용). 버전에 따라 순서대로 시도해 호환을 흡수한다.
        """
        cache = self.__dict__.setdefault("_ppocr_by_lang", {})
        if lang not in cache:
            from paddleocr import PaddleOCR
            for kwargs in (
                {"lang": lang, "use_textline_orientation": True},          # 3.x (PP-OCRv5)
                {"lang": lang, "use_angle_cls": True, "show_log": False},  # 2.x
                {"lang": lang},                                            # 최소 인자
            ):
                try:
                    cache[lang] = PaddleOCR(**kwargs)
                    break
                except TypeError:
                    continue
            else:
                cache[lang] = PaddleOCR(lang=lang)
        return cache[lang]

    @cached_property
    def inpainter(self):
        """LaMa 망가 인페인팅.

        우선순위:
          1. models/anime-manga-big-lama.pt  → TorchScript JIT
          2. models/lama-manga-dynamic.onnx  → ONNX Runtime

        반환: ("jit", model, device)  또는  ("onnx", session)
        """
        import torch
        from app.config import settings

        model_dir = Path(settings.model_dir)
        jit_path = model_dir / "anime-manga-big-lama.pt"
        onnx_path = model_dir / "lama-manga-dynamic.onnx"

        if jit_path.exists():
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = torch.jit.load(str(jit_path), map_location=device).eval()
            return ("jit", model, device)

        if onnx_path.exists():
            import onnxruntime as ort
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if torch.cuda.is_available()
                else ["CPUExecutionProvider"]
            )
            sess = ort.InferenceSession(str(onnx_path), providers=providers)
            return ("onnx", sess)

        raise FileNotFoundError(
            "LaMa 모델을 찾을 수 없습니다.\n"
            f"  JIT : {jit_path}\n"
            f"  ONNX: {onnx_path}\n"
            "models/ 디렉터리에 해당 파일을 배치하세요 (CLAUDE.md §6 참조)."
        )

    def status(self) -> dict[str, bool]:
        """각 모델의 로딩 여부(헬스체크용). cached_property 캐시 존재로 판단."""
        return {
            "detector": "detector" in self.__dict__,
            "ocr_ja": "ocr_ja" in self.__dict__,
            "ocr_ppocr": bool(self.__dict__.get("_ppocr_by_lang")),
            "inpainter": "inpainter" in self.__dict__,
        }

    def warmup(self) -> None:
        """콜드스타트 단축용 사전 로딩(선택)."""
        _ = self.detector, self.ocr_ja, self.inpainter
        self.ocr_ppocr("en")


registry = ModelRegistry()
