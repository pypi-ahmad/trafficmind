"""Inference pipeline — composes detection, tracking, OCR, and rules per frame.

The pipeline is stateful (owns a tracker instance) but does not own the
frame loop.  The worker calls ``process_frame()`` for each frame it reads.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from services.ocr.config import OcrSettings, get_ocr_settings
from services.ocr.interface import OcrEngine, OcrEngineRegistry
from services.ocr.pipeline import read_plate
from services.ocr.schemas import PlateOcrResult
from services.rules.engine import RulesEngine
from services.rules.schemas import SceneContext, SignalIntegrationMode, ViolationRecord, ZoneConfig
from services.signals.classifier import SignalClassifier, SignalClassifierRegistry
from services.signals.config import SignalSettings, get_signal_settings
from services.signals.integration import ControllerSignalSnapshot, SignalIntegrationService
from services.signals.schemas import SignalHeadConfig, SignalSceneSnapshot
from services.signals.state import SignalStateTracker
from services.streams.events import PerceptionEventBatch, build_perception_event_batch
from services.streams.schemas import PipelineFlags
from services.tracking.config import TrackingSettings, get_tracking_settings
from services.tracking.interface import Tracker, TrackerRegistry
from services.tracking.schemas import TrackingResult
from services.vision.config import VisionSettings, get_vision_settings
from services.vision.interface import Detector, DetectorRegistry
from services.vision.schemas import DetectionResult, ObjectCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameResult:
    """Output of a single pipeline pass on one frame."""

    frame_index: int
    timestamp: datetime
    elapsed_ms: float
    detection_result: DetectionResult | None = None
    tracking_result: TrackingResult | None = None
    signal_snapshot: SignalSceneSnapshot | None = None
    controller_signal_snapshot: ControllerSignalSnapshot | None = None
    scene_context: SceneContext | None = None
    event_batch: PerceptionEventBatch | None = None
    plate_reads: list[PlateOcrResult] = field(default_factory=list)
    violations: list[ViolationRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def detection_count(self) -> int:
        return self.detection_result.count if self.detection_result else 0

    @property
    def active_tracks(self) -> int:
        return self.tracking_result.active_count if self.tracking_result else 0

    @property
    def event_count(self) -> int:
        return self.event_batch.event_count if self.event_batch is not None else 0


class FramePipeline:
    """Stateful per-job pipeline that composes vision stages.

    Call ``start()`` before processing frames and ``stop()`` when done.
    The pipeline is **not** thread-safe — one instance per worker.
    """

    def __init__(
        self,
        flags: PipelineFlags,
        *,
        vision_settings: VisionSettings | None = None,
        tracking_settings: TrackingSettings | None = None,
        signal_settings: SignalSettings | None = None,
        ocr_settings: OcrSettings | None = None,
        signal_head_configs: list[SignalHeadConfig] | None = None,
        detector_factory: Callable[[], Detector] | None = None,
        tracker_factory: Callable[[], Tracker] | None = None,
        signal_classifier_factory: Callable[[], SignalClassifier] | None = None,
        ocr_engine_factory: Callable[[], OcrEngine] | None = None,
        zone_configs: list[ZoneConfig] | None = None,
        controller_signal_provider: Callable[..., ControllerSignalSnapshot | None] | None = None,
        signal_integration_service: SignalIntegrationService | None = None,
        signal_integration_mode: SignalIntegrationMode = SignalIntegrationMode.HYBRID,
    ) -> None:
        self._flags = flags
        self._vision_settings = vision_settings or get_vision_settings()
        self._tracking_settings = tracking_settings or get_tracking_settings()
        self._signal_settings = signal_settings or get_signal_settings()
        self._ocr_settings = ocr_settings or get_ocr_settings()
        self._signal_head_configs = list(signal_head_configs or [])
        self._zone_configs = list(zone_configs or [])
        self._detector_factory = detector_factory
        self._tracker_factory = tracker_factory
        self._signal_classifier_factory = signal_classifier_factory
        self._ocr_engine_factory = ocr_engine_factory
        self._controller_signal_provider = controller_signal_provider
        self._signal_integration_service = signal_integration_service or (
            SignalIntegrationService(
                vision_min_confidence=self._signal_settings.confidence_threshold
            )
            if controller_signal_provider is not None
            else None
        )
        self._signal_integration_mode = signal_integration_mode
        self._detector: Detector | None = None
        self._tracker: Tracker | None = None
        self._signal_tracker: SignalStateTracker | None = None
        self._ocr_engine: OcrEngine | None = None
        self._rules_engine: RulesEngine | None = None
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    def start(self) -> None:
        """Load models and allocate resources."""
        if self._started:
            return

        if self._flags.detection:
            self._detector = (
                self._detector_factory()
                if self._detector_factory is not None
                else DetectorRegistry.create("yolo", self._vision_settings)
            )
            self._detector.load_model()
            logger.info("Pipeline: detection stage loaded")

        if self._flags.tracking:
            self._tracker = (
                self._tracker_factory()
                if self._tracker_factory is not None
                else TrackerRegistry.create(
                    self._tracking_settings.backend,
                    self._tracking_settings,
                )
            )
            logger.info("Pipeline: tracking stage loaded")

        if self._flags.signals and self._flags.detection:
            classifier = (
                self._signal_classifier_factory()
                if self._signal_classifier_factory is not None
                else SignalClassifierRegistry.create(
                    self._signal_settings.backend,
                    self._signal_settings,
                )
            )
            classifier.load()
            self._signal_tracker = SignalStateTracker(
                classifier,
                self._signal_settings,
                head_configs=self._signal_head_configs,
            )
            logger.info("Pipeline: signal classification stage loaded")

        if self._flags.ocr and self._flags.detection:
            self._ocr_engine = (
                self._ocr_engine_factory()
                if self._ocr_engine_factory is not None
                else OcrEngineRegistry.create(self._ocr_settings.backend, self._ocr_settings)
            )
            self._ocr_engine.load_model()
            logger.info("Pipeline: OCR stage loaded")

        if self._flags.rules and self._flags.tracking:
            self._rules_engine = RulesEngine(self._zone_configs)
            logger.info(
                "Pipeline: rules stage loaded (%d zones)", len(self._zone_configs)
            )

        self._started = True

    def stop(self) -> None:
        """Release models and resources."""
        if self._detector is not None:
            self._detector.unload()
            self._detector = None

        if self._tracker is not None:
            self._tracker.reset()
            self._tracker = None

        if self._signal_tracker is not None:
            self._signal_tracker.reset()
            self._signal_tracker = None

        if self._ocr_engine is not None:
            self._ocr_engine.unload()
            self._ocr_engine = None

        if self._rules_engine is not None:
            self._rules_engine.reset()
            self._rules_engine = None

        self._started = False
        logger.info("Pipeline stopped")

    def process_frame(
        self,
        frame: np.ndarray,
        *,
        frame_index: int,
        source_id: str = "unknown",
        stream_id: uuid.UUID | None = None,
        camera_id: uuid.UUID | None = None,
        timestamp: datetime | None = None,
        source_width: int | None = None,
        source_height: int | None = None,
    ) -> FrameResult:
        """Run all enabled pipeline stages on a single frame."""

        ts = timestamp or datetime.now(UTC)
        t0 = time.perf_counter()

        detection_result: DetectionResult | None = None
        tracking_result: TrackingResult | None = None
        plate_reads: list[PlateOcrResult] = []
        violations: list[ViolationRecord] = []

        if self._detector is not None:
            detection_result = self._detector.detect(
                frame,
                frame_index=frame_index,
                timestamp=ts,
            )

        if self._tracker is not None and detection_result is not None:
            tracking_result = self._tracker.update(detection_result)

        # ── OCR on detected plates ──────────────────────────────────
        if self._ocr_engine is not None and detection_result is not None:
            for det in detection_result.detections:
                if det.category != ObjectCategory.PLATE:
                    continue
                try:
                    result = read_plate(
                        frame,
                        bbox=det.bbox,
                        engine=self._ocr_engine,
                        settings=self._ocr_settings,
                        frame_index=frame_index,
                        timestamp=ts,
                    )
                    if result is not None:
                        plate_reads.append(result)
                except Exception:
                    logger.debug(
                        "OCR failed for plate bbox on frame %d", frame_index, exc_info=True
                    )

        # ── Signal classification ───────────────────────────────────
        signal_snapshot: SignalSceneSnapshot | None = None
        controller_signal_snapshot: ControllerSignalSnapshot | None = None
        vision_scene_context: SceneContext | None = None
        scene_context: SceneContext | None = None
        if self._signal_tracker is not None and detection_result is not None:
            signal_snapshot = self._signal_tracker.update(
                detection_result,
                frame,
                frame_index,
                ts,
                source_id=source_id,
                stream_id=stream_id,
                camera_id=camera_id,
            )
            vision_scene_context = self._signal_tracker.to_scene_context(frame_index, ts)

        if self._controller_signal_provider is not None:
            controller_signal_snapshot = self._controller_signal_provider(
                frame_index=frame_index,
                source_id=source_id,
                stream_id=stream_id,
                camera_id=camera_id,
                timestamp=ts,
            )
        elif self._signal_integration_service is not None and camera_id is not None:
            controller_signal_snapshot = self._signal_integration_service.get_controller_snapshot(
                camera_id=camera_id,
                at_time=ts,
            )

        if self._signal_integration_service is not None and (
            vision_scene_context is not None
            or (
                controller_signal_snapshot is not None and controller_signal_snapshot.signal_states
            )
        ):
            scene_context = self._signal_integration_service.resolve_scene_context(
                vision_scene=vision_scene_context,
                controller_snapshot=controller_signal_snapshot,
                camera_id=camera_id,
                timestamp=ts,
                mode=self._signal_integration_mode,
            )
        else:
            scene_context = vision_scene_context

        # ── Rules evaluation ────────────────────────────────────────
        if self._rules_engine is not None and tracking_result is not None:
            violations = self._rules_engine.evaluate(tracking_result, scene=scene_context)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        event_batch = build_perception_event_batch(
            source_id=source_id,
            stream_id=stream_id,
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp=ts,
            processing_latency_ms=elapsed_ms,
            detection_result=detection_result,
            tracking_result=tracking_result,
            signal_snapshot=signal_snapshot,
            source_width=source_width or frame.shape[1],
            source_height=source_height or frame.shape[0],
        )

        return FrameResult(
            frame_index=frame_index,
            timestamp=ts,
            elapsed_ms=elapsed_ms,
            detection_result=detection_result,
            tracking_result=tracking_result,
            signal_snapshot=signal_snapshot,
            scene_context=scene_context,
            controller_signal_snapshot=controller_signal_snapshot,
            event_batch=event_batch,
            plate_reads=plate_reads,
            violations=violations,
            metadata={
                "source_id": source_id,
                "source_width": source_width or frame.shape[1],
                "source_height": source_height or frame.shape[0],
            },
        )

    def __enter__(self) -> FramePipeline:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
