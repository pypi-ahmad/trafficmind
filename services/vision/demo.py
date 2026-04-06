"""Demo / test entrypoint for running local vision inference.

Usage::

    # Single image
    python -m services.vision.demo path/to/image.jpg

    # Video file (process every Nth frame)
    python -m services.vision.demo path/to/video.mp4 --frame-step 5

    # Webcam (device 0)
    python -m services.vision.demo 0

    # Swap backend or override device / threshold
    python -m services.vision.demo image.jpg --backend yolo --device cuda --confidence 0.35

The entrypoint resolves detectors through ``DetectorRegistry`` so future model
swapping does not require changing this CLI.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from services.vision.config import VisionSettings
from services.vision.interface import Detector, DetectorRegistry
from services.vision.schemas import DetectionResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.vision.demo",
        description="Run TrafficMind vision inference on a local image, video, or webcam.",
    )
    parser.add_argument(
        "source",
        help="Path to image/video file, or integer webcam device index.",
    )
    parser.add_argument(
        "--backend",
        default="yolo",
        help="Detector backend name (default: yolo).",
    )
    parser.add_argument("--device", default=None, help="Torch device override (cpu, cuda, cuda:0).")
    parser.add_argument("--confidence", type=float, default=None, help="Confidence threshold override.")
    parser.add_argument("--frame-step", type=int, default=1, help="Process every Nth frame (video only).")
    parser.add_argument("--max-frames", type=int, default=None, help="Stop after N processed frames.")
    parser.add_argument("--annotate", default=None, help="Write annotated output to this path.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print results as JSON.")
    return parser


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def _print_result(result: DetectionResult, *, as_json: bool = False) -> None:
    if as_json:
        payload = {
            "frame_index": result.frame_index,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "count": result.count,
            "inference_ms": result.inference_ms,
            "detections": [d.model_dump(mode="json") for d in result.detections],
        }
        print(json.dumps(payload, indent=2))
        return

    print(
        f"  frame={result.frame_index}  "
        f"detections={result.count}  "
        f"vehicles={len(result.vehicles)}  "
        f"people={len(result.people)}  "
        f"lights={len(result.traffic_lights)}  "
        f"inference={result.inference_ms:.1f}ms"
    )
    for detection in result.detections:
        bbox = detection.bbox
        print(
            f"    {detection.category.value:14s}  {detection.class_name:16s}  "
            f"conf={detection.confidence:.3f}  "
            f"bbox=({bbox.x1:.0f},{bbox.y1:.0f},{bbox.x2:.0f},{bbox.y2:.0f})"
        )


def _annotate_frame(frame: np.ndarray, result: DetectionResult) -> np.ndarray:
    """Draw boxes + labels using supervision if available, else plain OpenCV."""
    try:
        import supervision as sv

        detections = result.to_supervision()
        labels = [f"{d.class_name} {d.confidence:.2f}" for d in result.detections]
        annotated = sv.BoxAnnotator().annotate(frame.copy(), detections)
        return sv.LabelAnnotator().annotate(annotated, detections, labels=labels)
    except ImportError:
        output = frame.copy()
        for detection in result.detections:
            bbox = detection.bbox
            cv2.rectangle(
                output,
                (int(bbox.x1), int(bbox.y1)),
                (int(bbox.x2), int(bbox.y2)),
                (0, 255, 0),
                2,
            )
            cv2.putText(
                output,
                f"{detection.class_name} {detection.confidence:.2f}",
                (int(bbox.x1), int(bbox.y1) - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
            )
        return output


def run_on_image(
    detector: Detector,
    path: Path,
    *,
    confidence: float | None,
    as_json: bool,
    annotate_path: str | None,
) -> None:
    image = cv2.imread(str(path))
    if image is None:
        logger.error("Cannot read image: %s", path)
        sys.exit(1)

    result = detector.detect(
        image,
        frame_index=0,
        timestamp=datetime.now(timezone.utc),
        confidence=confidence,
    )
    _print_result(result, as_json=as_json)

    if annotate_path:
        annotated = _annotate_frame(image, result)
        cv2.imwrite(annotate_path, annotated)
        logger.info("Annotated image saved to %s", annotate_path)


def run_on_video(
    detector: Detector,
    source: str,
    *,
    frame_step: int,
    max_frames: int | None,
    confidence: float | None,
    as_json: bool,
    annotate_path: str | None,
) -> None:
    cap_source: int | str = int(source) if source.isdigit() else source
    capture = cv2.VideoCapture(cap_source)
    if not capture.isOpened():
        logger.error("Cannot open video source: %s", source)
        sys.exit(1)

    writer: cv2.VideoWriter | None = None
    if annotate_path:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = cv2.VideoWriter(annotate_path, fourcc, fps, (width, height))

    frame_index = 0
    processed = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % frame_step != 0:
                frame_index += 1
                continue

            result = detector.detect(
                frame,
                frame_index=frame_index,
                timestamp=datetime.now(timezone.utc),
                confidence=confidence,
            )
            _print_result(result, as_json=as_json)

            if writer is not None:
                writer.write(_annotate_frame(frame, result))

            frame_index += 1
            processed += 1
            if max_frames and processed >= max_frames:
                break
    finally:
        capture.release()
        if writer is not None:
            writer.release()

    logger.info("Processed %d frames from %s", processed, source)


def main() -> None:
    args = _build_parser().parse_args()

    settings_kwargs: dict[str, object] = {}
    if args.device:
        settings_kwargs["device"] = args.device
    settings = VisionSettings(**settings_kwargs)

    with DetectorRegistry.create(args.backend, settings) as detector:
        source_path = Path(args.source)
        if source_path.exists() and _is_image(source_path):
            run_on_image(
                detector,
                source_path,
                confidence=args.confidence,
                as_json=args.json_output,
                annotate_path=args.annotate,
            )
        else:
            run_on_video(
                detector,
                args.source,
                frame_step=args.frame_step,
                max_frames=args.max_frames,
                confidence=args.confidence,
                as_json=args.json_output,
                annotate_path=args.annotate,
            )


if __name__ == "__main__":
    main()
