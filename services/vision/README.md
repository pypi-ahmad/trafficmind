# Vision Service

Purpose:

- traffic-scene object detection
- traffic-light object localization
- frame-level scene understanding that remains deterministic

This service should wrap model loading and inference, not HTTP concerns.

Runtime defaults:

- prefer CUDA automatically when available
- enable FP16 inference by default on CUDA
- allow explicit override via `VISION_DEVICE=cpu|cuda|cuda:0`
