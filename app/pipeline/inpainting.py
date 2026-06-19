"""4) 인페인팅 — 망가 파인튜닝 LaMa 로 원문 텍스트 제거.

두 참고 프로젝트 모두 manga/anime 파인튜닝 LaMa 로 수렴:
  - comic-translate: anime-manga-big-lama.pt (TorchScript JIT) 또는
                     lama-manga-dynamic.onnx (ONNX)
  - BallonsTranslator: lama_large_512px.ckpt (dreMaz/AnimeMangaInpainting)

입력: RGB [H,W,C] + mask [H,W], 출력: 동일 크기. pad_mod=8 (8의 배수로 패딩).
대안 엔진: AOT, MI-GAN (registry 에서 교체 가능하도록 설계).
"""
from __future__ import annotations

from PIL import Image

from app.models.registry import registry
from app.schemas.options import InpaintOptions, InpainterName

_PAD_MOD = 8  # LaMa 입력 크기는 반드시 8의 배수


def inpaint(img: Image.Image, mask: Image.Image, opts: InpaintOptions) -> Image.Image:
    """마스크 영역을 복원해 원문이 지워진 깨끗한 이미지를 반환.

    - inpainter == none : 인페인팅 생략(원문 위에 바로 식자). 디버그/경량 옵션.
    - lama / aot        : 망가 LaMa (Colab/GPU 필요).
    """
    if opts.inpainter == InpainterName.NONE:
        return img.copy()

    backend = registry.inpainter

    import numpy as np
    img_arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0   # (H,W,3)  [0,1]
    mask_arr = np.array(mask.convert("L")).astype(np.float32) / 255.0   # (H,W)    [0,1]
    h, w = img_arr.shape[:2]

    # 8의 배수로 패딩 (LaMa 아키텍처 요구사항)
    ph = (_PAD_MOD - h % _PAD_MOD) % _PAD_MOD
    pw = (_PAD_MOD - w % _PAD_MOD) % _PAD_MOD
    if ph or pw:
        img_arr = np.pad(img_arr, ((0, ph), (0, pw), (0, 0)), mode="reflect")
        mask_arr = np.pad(mask_arr, ((0, ph), (0, pw)), mode="reflect")

    kind = backend[0]
    if kind == "jit":
        out_arr = _run_jit(backend, img_arr, mask_arr)
    else:
        out_arr = _run_onnx(backend, img_arr, mask_arr)

    # 패딩 제거 + uint8 변환
    out_arr = np.clip(out_arr[:h, :w] * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(out_arr)


def _run_jit(backend, img_arr, mask_arr):
    """TorchScript JIT 모델 추론 → (H,W,3) float32 [0,1]."""
    import torch
    _, model, device = backend
    img_t = torch.from_numpy(img_arr).permute(2, 0, 1).unsqueeze(0).to(device)   # (1,3,H,W)
    mask_t = torch.from_numpy(mask_arr).unsqueeze(0).unsqueeze(0).to(device)     # (1,1,H,W)
    with torch.no_grad():
        out = model(img_t, mask_t)
    return out.squeeze(0).permute(1, 2, 0).cpu().numpy()                          # (H,W,3)


def _run_onnx(backend, img_arr, mask_arr):
    """ONNX Runtime 세션 추론 → (H,W,3) float32 [0,1].

    입력 이름 "image"/"mask" 는 lama-manga-dynamic.onnx 기준.
    모델에 따라 다를 수 있으면 sess.get_inputs()[i].name 으로 확인.
    """
    _, sess = backend
    img_t = img_arr.transpose(2, 0, 1)[None].astype(np.float32)   # (1,3,H,W)
    mask_t = mask_arr[None, None].astype(np.float32)               # (1,1,H,W)
    out_t = sess.run(None, {"image": img_t, "mask": mask_t})[0]   # (1,3,H,W)
    return out_t.squeeze(0).transpose(1, 2, 0)                     # (H,W,3)
