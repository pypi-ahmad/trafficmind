"""Temporal signal-state tracker with hysteresis smoothing.

Owns per-signal-head state across frames.  Receives raw per-frame
classifications from the classifier, applies majority-vote smoothing,
and emits a stable ``SignalSceneSnapshot`` that downstream consumers
(rules engine, persistence layer) can trust.

Key design decisions:
  - **Hysteresis**: A signal head does not change its ``confirmed_color``
    until the new colour wins N consecutive majority votes.  This prevents
    noisy flicker on borderline frames from causing false violations.
  - **Spatial matching**: When no operator-configured head IDs exist, signal
    heads are assigned temporary IDs based on bbox IoU matching against
    previously seen positions.  This is sufficient for stationary cameras.
  - **Unknown on absence**: If a signal head is not observed for
    ``unknown_after_missed_frames`` consecutive frames, its confirmed colour
    reverts to UNKNOWN to avoid stale state driving rule evaluation.
  - **Multiple heads**: Each tracked head is independent.  Callers can query
    a specific head (by id, by phase, by linked zone) or simply ask for the
    primary vehicle signal.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime

import numpy as np

from services.rules.schemas import (
    SceneContext,
    SceneSignalState,
    SignalIntegrationMode,
    SignalStateSourceKind,
    TrafficLightState,
)
from services.signals.classifier import SignalClassifier
from services.signals.config import SignalSettings
from services.signals.schemas import (
    SignalClassification,
    SignalColor,
    SignalHeadConfig,
    SignalHeadObservation,
    SignalHeadState,
    SignalPhase,
    SignalSceneSnapshot,
)
from services.vision.schemas import BBox, DetectionResult

logger = logging.getLogger(__name__)


def _iou(a: BBox, b: BBox) -> float:
    """Compute Intersection-over-Union between two bounding boxes."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _majority_color(history: deque[SignalColor]) -> SignalColor:
    """Return the most common colour in the window, or UNKNOWN on ties."""
    if not history:
        return SignalColor.UNKNOWN
    counts: dict[SignalColor, int] = {}
    for c in history:
        counts[c] = counts.get(c, 0) + 1
    best = max(counts, key=counts.get)  # type: ignore[arg-type]
    # Tie-break: if UNKNOWN ties with a real colour, prefer UNKNOWN (safe)
    if counts.get(SignalColor.UNKNOWN, 0) == counts[best] and best != SignalColor.UNKNOWN:
        return SignalColor.UNKNOWN
    return best


def signal_color_to_traffic_light_state(color: SignalColor) -> TrafficLightState:
    """Map perception-layer ``SignalColor`` to rules-layer ``TrafficLightState``."""
    _MAP = {
        SignalColor.RED: TrafficLightState.RED,
        SignalColor.YELLOW: TrafficLightState.YELLOW,
        SignalColor.GREEN: TrafficLightState.GREEN,
        SignalColor.UNKNOWN: TrafficLightState.UNKNOWN,
    }
    return _MAP.get(color, TrafficLightState.UNKNOWN)


class _TrackedHead:
    """Internal mutable state for one signal head."""

    __slots__ = (
        "bbox",
        "confirmed_color",
        "confirmed_confidence",
        "consecutive_votes",
        "crosswalk_id",
        "head_id",
        "history",
        "lane_id",
        "last_seen_at",
        "last_seen_frame",
        "phase",
        "stop_line_id",
    )

    def __init__(
        self,
        head_id: str,
        phase: SignalPhase,
        bbox: BBox | None,
        window_size: int,
        *,
        lane_id: str | None = None,
        stop_line_id: str | None = None,
        crosswalk_id: str | None = None,
    ) -> None:
        self.head_id = head_id
        self.phase = phase
        self.bbox = bbox
        self.history: deque[SignalColor] = deque(maxlen=window_size)
        self.confirmed_color = SignalColor.UNKNOWN
        self.confirmed_confidence: float = 0.0
        self.consecutive_votes: int = 0
        self.last_seen_frame: int = 0
        self.last_seen_at: datetime | None = None
        self.lane_id = lane_id
        self.stop_line_id = stop_line_id
        self.crosswalk_id = crosswalk_id

    def to_state(
        self,
        *,
        current_frame: int,
        unknown_threshold: int,
        source_id: str | None,
        stream_id: uuid.UUID | None,
        camera_id: uuid.UUID | None,
    ) -> SignalHeadState:
        frames_since = current_frame - self.last_seen_frame
        is_stale = frames_since > unknown_threshold
        color = SignalColor.UNKNOWN if is_stale else self.confirmed_color
        return SignalHeadState(
            head_id=self.head_id,
            phase=self.phase,
            raw_color=self.history[-1] if self.history else SignalColor.UNKNOWN,
            confirmed_color=color,
            confidence=self.confirmed_confidence,
            last_seen_frame=self.last_seen_frame,
            last_seen_at=self.last_seen_at,
            frames_since_seen=frames_since,
            is_stale=is_stale,
            bbox=self.bbox,
            source_id=source_id,
            stream_id=stream_id,
            camera_id=camera_id,
            lane_id=self.lane_id,
            stop_line_id=self.stop_line_id,
            crosswalk_id=self.crosswalk_id,
        )


class SignalStateTracker:
    """Per-camera signal state tracker with temporal smoothing.

    Usage::

        tracker = SignalStateTracker(classifier, settings)
        snapshot = tracker.update(detection_result, frame, frame_index, timestamp)
        scene_ctx = tracker.to_scene_context(frame_index, timestamp)
    """

    IOU_MATCH_THRESHOLD = 0.3

    def __init__(
        self,
        classifier: SignalClassifier,
        settings: SignalSettings,
        *,
        head_configs: list[SignalHeadConfig] | None = None,
    ) -> None:
        self._classifier = classifier
        self._settings = settings
        self._heads: dict[str, _TrackedHead] = {}
        self._next_anon_id = 0
        self._head_configs = list(head_configs or [])
        self._last_source_id: str | None = None
        self._last_stream_id: uuid.UUID | None = None
        self._last_camera_id: uuid.UUID | None = None

        self._seed_configured_heads()

    def _seed_configured_heads(self) -> None:
        for cfg in self._head_configs:
            self._heads[cfg.head_id] = _TrackedHead(
                head_id=cfg.head_id,
                phase=cfg.phase,
                bbox=cfg.anchor_bbox,
                window_size=self._settings.smoothing_window,
                lane_id=cfg.lane_id,
                stop_line_id=cfg.stop_line_id,
                crosswalk_id=cfg.crosswalk_id,
            )

    @property
    def head_count(self) -> int:
        return len(self._heads)

    def update(
        self,
        detection_result: DetectionResult | None,
        frame: np.ndarray,
        frame_index: int,
        timestamp: datetime,
        *,
        source_id: str | None = None,
        stream_id: uuid.UUID | None = None,
        camera_id: uuid.UUID | None = None,
    ) -> SignalSceneSnapshot:
        """Process one frame: extract signal crops → classify → smooth → snapshot."""
        self._last_source_id = source_id
        self._last_stream_id = stream_id
        self._last_camera_id = camera_id
        observations: list[SignalHeadObservation] = []

        if detection_result is not None:
            tl_detections = detection_result.traffic_lights
            for det in tl_detections:
                crop = self._extract_crop(frame, det.bbox)
                if crop is None:
                    continue

                classification = self._classifier.classify(crop)
                head = self._match_or_create_head(det.bbox)
                self._push_observation(head, classification, frame_index, timestamp, det.bbox)

                observations.append(
                    SignalHeadObservation(
                        head_id=head.head_id,
                        phase=head.phase,
                        bbox=det.bbox,
                        classification=classification,
                        frame_index=frame_index,
                        timestamp=timestamp,
                        source_id=source_id,
                        stream_id=stream_id,
                        camera_id=camera_id,
                        lane_id=head.lane_id,
                        stop_line_id=head.stop_line_id,
                        crosswalk_id=head.crosswalk_id,
                    )
                )

        head_states = [
            h.to_state(
                current_frame=frame_index,
                unknown_threshold=self._settings.unknown_after_missed_frames,
                source_id=source_id,
                stream_id=stream_id,
                camera_id=camera_id,
            )
            for h in self._heads.values()
        ]

        return SignalSceneSnapshot(
            frame_index=frame_index,
            timestamp=timestamp,
            source_id=source_id,
            stream_id=stream_id,
            camera_id=camera_id,
            observations=observations,
            head_states=head_states,
        )

    def to_scene_context(
        self,
        frame_index: int,
        timestamp: datetime,
    ) -> SceneContext:
        """Build a ``SceneContext`` from the current smoothed signal state.

        Uses the primary explicit vehicle-phase signal head. If no vehicle
        head is configured, returns ``TrafficLightState.UNKNOWN`` — safe for
        downstream consumers since all red-light rules skip evaluation when
        the state is UNKNOWN.
        """
        states = self._scene_signal_states(frame_index)
        primary_vehicle = self._unique_phase_state(states, phase=SignalPhase.VEHICLE)
        primary_pedestrian = self._unique_phase_state(states, phase=SignalPhase.PEDESTRIAN)
        vehicle_state = (
            primary_vehicle.state if primary_vehicle is not None else TrafficLightState.UNKNOWN
        )
        pedestrian_state = (
            primary_pedestrian.state
            if primary_pedestrian is not None
            else TrafficLightState.UNKNOWN
        )

        return SceneContext(
            frame_index=frame_index,
            timestamp=timestamp,
            traffic_light_state=vehicle_state,
            traffic_light_zone_name=primary_vehicle.stop_line_id
            if primary_vehicle is not None
            else None,
            vehicle_signal_state=vehicle_state,
            pedestrian_signal_state=pedestrian_state,
            signal_states=states,
            vision_signal_states=states,
            integration_mode=SignalIntegrationMode.VISION_ONLY,
        )

    @staticmethod
    def _unique_phase_state(
        states: list[SceneSignalState],
        *,
        phase: SignalPhase,
    ) -> SceneSignalState | None:
        phase_states = [state for state in states if state.phase == phase]
        if len(phase_states) != 1:
            return None
        return phase_states[0]

    def reset(self) -> None:
        """Clear tracked state while preserving configured signal heads."""
        self._heads.clear()
        self._next_anon_id = 0
        self._last_source_id = None
        self._last_stream_id = None
        self._last_camera_id = None
        self._seed_configured_heads()

    def _scene_signal_states(self, frame_index: int) -> list[SceneSignalState]:
        states: list[SceneSignalState] = []
        for head in self._heads.values():
            state = head.to_state(
                current_frame=frame_index,
                unknown_threshold=self._settings.unknown_after_missed_frames,
                source_id=self._last_source_id,
                stream_id=self._last_stream_id,
                camera_id=self._last_camera_id,
            )
            states.append(
                SceneSignalState(
                    head_id=state.head_id,
                    phase=state.phase,
                    state=signal_color_to_traffic_light_state(state.confirmed_color),
                    confidence=state.confidence,
                    trust_score=state.confidence,
                    frame_index=frame_index,
                    last_seen_at=state.last_seen_at,
                    frames_since_seen=state.frames_since_seen,
                    is_stale=state.is_stale,
                    source_id=state.source_id,
                    stream_id=state.stream_id,
                    camera_id=state.camera_id,
                    lane_id=state.lane_id,
                    stop_line_id=state.stop_line_id,
                    crosswalk_id=state.crosswalk_id,
                    source_kind=SignalStateSourceKind.VISION,
                    observed_sources=[SignalStateSourceKind.VISION],
                )
            )
        return states

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_crop(self, frame: np.ndarray, bbox: BBox) -> np.ndarray | None:
        """Extract and validate a traffic-light crop from the full frame."""
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox.x1))
        y1 = max(0, int(bbox.y1))
        x2 = min(w, int(bbox.x2))
        y2 = min(h, int(bbox.y2))

        crop_w = x2 - x1
        crop_h = y2 - y1
        if crop_w < self._settings.min_crop_pixels or crop_h < self._settings.min_crop_pixels:
            return None

        return frame[y1:y2, x1:x2]

    def _match_or_create_head(self, bbox: BBox) -> _TrackedHead:
        """Match a detection bbox to an existing head by IoU, or create a new one."""
        best_head: _TrackedHead | None = None
        best_iou = self.IOU_MATCH_THRESHOLD

        for head in self._heads.values():
            if head.bbox is None:
                continue
            score = _iou(head.bbox, bbox)
            if score > best_iou:
                best_iou = score
                best_head = head

        if best_head is not None:
            return best_head

        # Create a new anonymous head
        head_id = f"signal-{self._next_anon_id}"
        self._next_anon_id += 1
        head = _TrackedHead(
            head_id=head_id,
            phase=SignalPhase.UNKNOWN,
            bbox=bbox,
            window_size=self._settings.smoothing_window,
        )
        self._heads[head_id] = head
        logger.debug("Created anonymous signal head %s at %s", head_id, bbox)
        return head

    def _push_observation(
        self,
        head: _TrackedHead,
        classification: SignalClassification,
        frame_index: int,
        timestamp: datetime,
        bbox: BBox,
    ) -> None:
        """Update a head's history and apply hysteresis."""
        head.bbox = bbox
        head.last_seen_frame = frame_index
        head.last_seen_at = timestamp
        head.history.append(classification.color)

        # Majority vote
        majority = _majority_color(head.history)

        # Hysteresis: require transition_threshold consecutive majority wins
        if majority == head.confirmed_color:
            head.consecutive_votes = len(head.history)
            head.confirmed_confidence = classification.confidence
        elif majority != SignalColor.UNKNOWN:
            head.consecutive_votes += 1
            if head.consecutive_votes >= self._settings.transition_threshold:
                prev = head.confirmed_color
                head.confirmed_color = majority
                head.confirmed_confidence = classification.confidence
                head.consecutive_votes = 0
                logger.info(
                    "Signal head %s transition: %s → %s (confidence=%.2f)",
                    head.head_id,
                    prev.value,
                    majority.value,
                    classification.confidence,
                )
        else:
            # Majority is UNKNOWN — reset consecutive counter but keep confirmed
            head.consecutive_votes = 0
