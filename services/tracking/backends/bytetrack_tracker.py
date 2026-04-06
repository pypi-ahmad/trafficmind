"""ByteTrack-backed multi-object tracker implementation."""

from __future__ import annotations

import supervision as sv

from services.tracking.config import TrackingSettings
from services.tracking.interface import MatchedDetection, StatefulTracker
from services.vision.schemas import BBox, DetectionResult, ObjectCategory


class ByteTrackTracker(StatefulTracker):
    """Stateful tracker built on supervision's ByteTrack implementation.

    All shared book-keeping (trajectory management, direction estimation,
    lifecycle active→lost→removed) is handled by ``StatefulTracker``.
    This class only converts detections into ByteTrack's format and
    extracts matched assignments.
    """

    def __init__(self, settings: TrackingSettings) -> None:
        super().__init__(settings)
        self._sv_tracker = self._build_sv_tracker()

    def _match(self, detections: DetectionResult) -> list[MatchedDetection]:
        tracked = self._sv_tracker.update_with_detections(detections.to_supervision())

        class_names = tracked.data.get("class_name", [])
        categories = tracked.data.get("category", [])
        matches: list[MatchedDetection] = []

        for index in range(len(tracked)):
            tracker_id_value = tracked.tracker_id[index]
            if tracker_id_value is None:
                continue

            track_id = str(int(tracker_id_value))
            class_name = str(class_names[index]) if len(class_names) > index else "unknown"
            category_value = str(categories[index]) if len(categories) > index else ObjectCategory.OTHER.value
            category = (
                ObjectCategory(category_value)
                if category_value in ObjectCategory._value2member_map_
                else ObjectCategory.OTHER
            )
            class_id: int | None = None
            if tracked.class_id is not None:
                raw = int(tracked.class_id[index])
                class_id = raw if raw >= 0 else None
            confidence = float(tracked.confidence[index]) if tracked.confidence is not None else 0.0
            x1, y1, x2, y2 = tracked.xyxy[index].tolist()

            matches.append(
                MatchedDetection(
                    track_id=track_id,
                    bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    class_name=class_name,
                    category=category,
                    class_id=class_id,
                    confidence=confidence,
                )
            )

        return matches

    def reset(self) -> None:
        super().reset()
        self._sv_tracker = self._build_sv_tracker()

    def _build_sv_tracker(self) -> sv.ByteTrack:
        return sv.ByteTrack(
            track_activation_threshold=self._settings.track_activation_threshold,
            lost_track_buffer=self._settings.lost_track_buffer,
            minimum_matching_threshold=self._settings.minimum_matching_threshold,
            frame_rate=self._settings.frame_rate,
            minimum_consecutive_frames=self._settings.minimum_consecutive_frames,
        )