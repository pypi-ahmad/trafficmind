"""Centroid-distance tracker — even simpler than IoU.

A minimal multi-object tracker that associates detections to existing
tracks using Euclidean distance between bounding-box centroids.  This is
the simplest possible stateful tracker and serves as:

* a **second proof** that the ``StatefulTracker`` / ``_match`` abstraction
  is sound (alongside the IoU and ByteTrack backends),
* a viable backend when objects change shape but move smoothly (e.g.
  top-down traffic cameras where bounding-box overlap is low), and
* a zero-external-dependency alternative for integration tests.

Algorithm per frame:
    1. Compute the centroid of every existing active track and every new
       detection.
    2. Build an (M × N) Euclidean distance matrix.
    3. Greedily assign the closest pair below ``max_centroid_distance``
       (derived from ``minimum_matching_threshold`` and frame diagonal).
    4. Unmatched detections become new tracks.
    5. Unmatched tracks follow the standard lost → removed lifecycle
       managed by ``StatefulTracker``.
"""

from __future__ import annotations

import numpy as np

from services.tracking.config import TrackingSettings
from services.tracking.interface import MatchedDetection, StatefulTracker
from services.vision.schemas import BBox, DetectionResult, ObjectCategory


def _centroid(bbox: BBox) -> tuple[float, float]:
    return bbox.center


class CentroidTracker(StatefulTracker):
    """Euclidean-distance centroid tracker.

    Inherits trajectory, direction, and lifecycle management from
    ``StatefulTracker``; only implements the ``_match`` hook.
    """

    def __init__(self, settings: TrackingSettings) -> None:
        super().__init__(settings)
        self._next_id = 1
        self._last_centroids: dict[str, tuple[float, float]] = {}

    def _match(self, detections: DetectionResult) -> list[MatchedDetection]:
        dets = detections.detections
        if not dets:
            return []

        active_ids = [
            tid for tid, t in self._tracks.items()
            if t.missed_frames == 0
        ]

        if not active_ids:
            return self._create_new(dets)

        det_centroids = [_centroid(d.bbox) for d in dets]
        track_centroids = [self._last_centroids[tid] for tid in active_ids]

        # Build Euclidean distance matrix.
        dist = np.zeros((len(active_ids), len(dets)), dtype=np.float64)
        for t_idx, (tx, ty) in enumerate(track_centroids):
            for d_idx, (dx, dy) in enumerate(det_centroids):
                dist[t_idx, d_idx] = np.sqrt((tx - dx) ** 2 + (ty - dy) ** 2)

        # Derive a pixel-distance threshold from the matching threshold
        # setting (0–1) scaled to the frame diagonal.  A threshold of 0.8
        # means "only match if the centroid moved less than 20% of the
        # frame diagonal".
        if detections.source_width and detections.source_height:
            diag = np.sqrt(detections.source_width ** 2 + detections.source_height ** 2)
        else:
            diag = 1000.0  # fallback

        max_dist = diag * (1.0 - self._settings.minimum_matching_threshold)

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        matches: list[MatchedDetection] = []

        flat_order = np.argsort(dist, axis=None)
        for flat_idx in flat_order:
            t_idx = int(flat_idx // len(dets))
            d_idx = int(flat_idx % len(dets))
            if t_idx in matched_tracks or d_idx in matched_dets:
                continue
            if dist[t_idx, d_idx] > max_dist:
                break
            matched_tracks.add(t_idx)
            matched_dets.add(d_idx)
            tid = active_ids[t_idx]
            det = dets[d_idx]
            self._last_centroids[tid] = _centroid(det.bbox)
            matches.append(self._det_to_match(det, tid))

        for d_idx, det in enumerate(dets):
            if d_idx not in matched_dets:
                matches.append(self._create_single(det))

        return matches

    def reset(self) -> None:
        super().reset()
        self._next_id = 1
        self._last_centroids.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_new(self, dets: list) -> list[MatchedDetection]:
        return [self._create_single(d) for d in dets]

    def _create_single(self, det) -> MatchedDetection:
        tid = str(self._next_id)
        self._next_id += 1
        self._last_centroids[tid] = _centroid(det.bbox)
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
