"""Greedy IoU tracker — zero external dependencies beyond numpy.

A lightweight multi-object tracker that associates detections to tracks
using Intersection-over-Union scores and greedy assignment.  This backend
validates the ``StatefulTracker`` abstraction without requiring the
``supervision`` library and serves as a practical fallback when ByteTrack
is unavailable.

Algorithm per frame:
    1. Compute IoU between every existing track's last bbox and every new
       detection.
    2. Greedily assign the highest-IoU pair above
       ``minimum_matching_threshold``.
    3. Unmatched detections become new tracks.
    4. Unmatched tracks are left for the ``StatefulTracker`` lost/removed
       lifecycle.
"""

from __future__ import annotations

import itertools

import numpy as np

from services.tracking.config import TrackingSettings
from services.tracking.interface import MatchedDetection, StatefulTracker
from services.vision.schemas import BBox, DetectionResult, ObjectCategory


def _iou(a: BBox, b: BBox) -> float:
    """Compute IoU between two axis-aligned bounding boxes."""
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter == 0.0:
        return 0.0
    area_a = a.area
    area_b = b.area
    return inter / (area_a + area_b - inter) if (area_a + area_b - inter) > 0 else 0.0


class IoUTracker(StatefulTracker):
    """Greedy IoU-based multi-object tracker.

    Inherits full trajectory, direction, and lifecycle management from
    ``StatefulTracker``; only implements the ``_match`` hook.
    """

    def __init__(self, settings: TrackingSettings) -> None:
        super().__init__(settings)
        self._next_id = 1
        # Lightweight per-track bbox cache for IoU computation.
        # The canonical track state lives in StatefulTracker._tracks.
        self._last_bboxes: dict[str, BBox] = {}

    def _match(self, detections: DetectionResult) -> list[MatchedDetection]:
        dets = detections.detections
        if not dets:
            return []

        active_ids = [
            tid for tid, t in self._tracks.items()
            if t.missed_frames == 0
        ]

        # Fast path: no existing tracks → all detections are new.
        if not active_ids:
            return self._create_new(dets)

        # Build IoU cost matrix.
        det_bboxes = [d.bbox for d in dets]
        track_bboxes = [self._last_bboxes[tid] for tid in active_ids]

        iou_matrix = np.zeros((len(active_ids), len(dets)), dtype=np.float64)
        for t_idx, t_bbox in enumerate(track_bboxes):
            for d_idx, d_bbox in enumerate(det_bboxes):
                iou_matrix[t_idx, d_idx] = _iou(t_bbox, d_bbox)

        threshold = self._settings.minimum_matching_threshold
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        matches: list[MatchedDetection] = []

        # Greedy assignment: pick the highest IoU pair each round.
        flat_order = np.argsort(iou_matrix, axis=None)[::-1]
        for flat_idx in flat_order:
            t_idx = int(flat_idx // len(dets))
            d_idx = int(flat_idx % len(dets))
            if t_idx in matched_tracks or d_idx in matched_dets:
                continue
            if iou_matrix[t_idx, d_idx] < threshold:
                break  # all remaining pairs are below threshold
            matched_tracks.add(t_idx)
            matched_dets.add(d_idx)
            tid = active_ids[t_idx]
            det = dets[d_idx]
            self._last_bboxes[tid] = det.bbox
            matches.append(self._det_to_match(det, tid))

        # New tracks for unmatched detections.
        for d_idx, det in enumerate(dets):
            if d_idx not in matched_dets:
                matches.append(self._create_single(det))

        return matches

    def reset(self) -> None:
        super().reset()
        self._next_id = 1
        self._last_bboxes.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_new(self, dets: list) -> list[MatchedDetection]:
        return [self._create_single(d) for d in dets]

    def _create_single(self, det) -> MatchedDetection:
        tid = str(self._next_id)
        self._next_id += 1
        self._last_bboxes[tid] = det.bbox
        return self._det_to_match(det, tid)

    @staticmethod
    def _det_to_match(det, tid: str) -> MatchedDetection:
        category = det.category if isinstance(det.category, ObjectCategory) else ObjectCategory.OTHER
        return MatchedDetection(
            track_id=tid,
            bbox=det.bbox,
            class_name=det.class_name,
            category=category,
            class_id=getattr(det, "class_id", None),
            confidence=det.confidence,
        )
