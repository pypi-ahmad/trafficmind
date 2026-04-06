# Vision Service

Purpose:

- traffic-scene object detection
- traffic-light object localization
- frame-level scene understanding that remains deterministic

This service should wrap model loading and inference, not HTTP concerns.

Runtime defaults:

- `VISION_DEVICE=auto` (default) → `cuda` when `torch.cuda.is_available()`, else `cpu`
- enable FP16 inference by default on CUDA (`VISION_HALF_PRECISION=true`)
- allow explicit override via `VISION_DEVICE=cpu|cuda|cuda:0`
- on a Windows machine with CUDA-capable PyTorch, auto resolves to `cuda`
