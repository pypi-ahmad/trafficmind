"""Tracker interface, stateful base, and backend registry."""

from __future__ import annotations

import abc
import importlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from services.tracking.schemas import (
    TrackedObject,
    TrackingResult,
    TrackLifecycleStatus,
    TrajectoryPoint,
)
from services.tracking.utils import centroid_from_bbox, estimate_direction

if TYPE_CHECKING:
    from services.tracking.config import TrackingSettings
    from services.vision.schemas import BBox, DetectionResult, ObjectCategory


class Tracker(abc.ABC):
    """Abstract multi-object tracker backend."""

    @abc.abstractmethod
    def update(self, detections: DetectionResult) -> TrackingResult:
        """Update tracker state from one frame's detections."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset internal state and restart track ids."""

    @abc.abstractmethod
    def get_active_tracks(self) -> list[TrackedObject]:
        """Return currently active tracks."""

    @abc.abstractmethod
    def snapshot(self, *, include_inactive: bool = False) -> list[TrackedObject]:
        """Return a snapshot of current tracker state.

        Backends **must** honour *include_inactive*: when ``True`` the
        result should include lost / recently-removed tracks that are
        still held in memory.
        """


@dataclass(frozen=True, slots=True)
class MatchedDetection:
    """Backend-neutral result of one detection→track assignment."""

    track_id: str
    bbox: BBox
    class_name: str
    category: ObjectCategory
    class_id: int | None
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


class StatefulTracker(Tracker):
    """Shared track-state book-keeping that any backend can inherit.

    Subclasses implement ``_match`` to run the backend-specific association
    algorithm and return a list of ``MatchedDetection`` objects.  This base
    class owns trajectory management, direction estimation, lifecycle
    (active → lost → removed), and output construction — logic that would
    otherwise be copy-pasted across every backend.
    """

    def __init__(self, settings: TrackingSettings) -> None:
        self._settings = settings
        self._tracks: dict[str, TrackedObject] = {}

    # ------------------------------------------------------------------
    # Abstract hook — the ONLY method a backend must implement
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _match(self, detections: DetectionResult) -> list[MatchedDetection]:
        """Run backend-specific matching and return track assignments."""

    # ------------------------------------------------------------------
    # Concrete Tracker interface
    # ------------------------------------------------------------------

    def update(self, detections: DetectionResult) -> TrackingResult:
        timestamp = detections.timestamp or datetime.now(timezone.utc)
        matches = self._match(detections)
        return self._reconcile(matches, detections.frame_index, timestamp)

    def reset(self) -> None:
        self._tracks.clear()

    def get_active_tracks(self) -> list[TrackedObject]:
        return [
            track.model_copy(deep=True)
            for track in self._tracks.values()
            if track.status == TrackLifecycleStatus.ACTIVE and track.missed_frames == 0
        ]

    def snapshot(self, *, include_inactive: bool = False) -> list[TrackedObject]:
        source = self._tracks.values() if include_inactive else (
            t for t in self._tracks.values()
            if t.status == TrackLifecycleStatus.ACTIVE and t.missed_frames == 0
        )
        return [track.model_copy(deep=True) for track in source]

    # ------------------------------------------------------------------
    # Shared reconciliation
    # ------------------------------------------------------------------

    def _reconcile(
        self,
        matches: list[MatchedDetection],
        frame_index: int | None,
        timestamp: datetime,
    ) -> TrackingResult:
        active_ids: set[str] = set()
        new_track_ids: list[str] = []
        lost_track_ids: list[str] = []
        lost_tracks: list[TrackedObject] = []
        removed_track_ids: list[str] = []
        removed_tracks: list[TrackedObject] = []
        active_tracks: list[TrackedObject] = []

        for m in matches:
            centroid = centroid_from_bbox(m.bbox)
            traj_pt = TrajectoryPoint(
                point=centroid,
                frame_index=frame_index,
                timestamp=timestamp,
            )

            track = self._tracks.get(m.track_id)
            if track is None:
                track = TrackedObject(
                    track_id=m.track_id,
                    class_name=m.class_name,
                    category=m.category,
                    class_id=m.class_id,
                    bbox=m.bbox,
                    confidence=m.confidence,
                    first_seen_at=timestamp,
                    last_seen_at=timestamp,
                    first_seen_frame=frame_index,
                    last_seen_frame=frame_index,
                    frame_count=1,
                    trajectory=[traj_pt],
                    missed_frames=0,
                    status=TrackLifecycleStatus.ACTIVE,
                )
                new_track_ids.append(m.track_id)
            else:
                track.class_name = m.class_name
                track.category = m.category
                track.class_id = m.class_id
                track.bbox = m.bbox
                track.confidence = m.confidence
                track.last_seen_at = timestamp
                track.last_seen_frame = frame_index
                track.frame_count += 1
                track.missed_frames = 0
                track.status = TrackLifecycleStatus.ACTIVE
                track.trajectory.append(traj_pt)
                if len(track.trajectory) > self._settings.trajectory_history_size:
                    track.trajectory = track.trajectory[-self._settings.trajectory_history_size:]

            track.direction = estimate_direction(track.trajectory)
            self._tracks[m.track_id] = track
            active_ids.add(m.track_id)
            active_tracks.append(track.model_copy(deep=True))

        # Lifecycle: active → lost → removed
        for track_id, track in list(self._tracks.items()):
            if track_id in active_ids:
                continue
            if track.status == TrackLifecycleStatus.ACTIVE:
                lost_track_ids.append(track_id)
            track.missed_frames += 1
            track.status = TrackLifecycleStatus.LOST
            if track_id in lost_track_ids:
                lost_tracks.append(track.model_copy(deep=True))
            if track.missed_frames > self._settings.lost_track_buffer:
                track.status = TrackLifecycleStatus.REMOVED
                removed_track_ids.append(track_id)
                removed_tracks.append(track.model_copy(deep=True))
                del self._tracks[track_id]

        return TrackingResult(
            tracks=active_tracks,
            frame_index=frame_index,
            timestamp=timestamp,
            new_track_ids=new_track_ids,
            lost_track_ids=lost_track_ids,
            lost_tracks=lost_tracks,
            removed_track_ids=removed_track_ids,
            removed_tracks=removed_tracks,
        )


class TrackerRegistry:
    """Name → tracker backend registry."""

    _backends: dict[str, type[Tracker]] = {}
    _lazy_backends: dict[str, str] = {
        "bytetrack": "services.tracking.backends.bytetrack_tracker:ByteTrackTracker",
        "centroid": "services.tracking.backends.centroid_tracker:CentroidTracker",
        "iou": "services.tracking.backends.iou_tracker:IoUTracker",
    }

    @classmethod
    def register(cls, name: str, backend_cls: type[Tracker]) -> None:
        cls._backends[name] = backend_cls

    @classmethod
    def register_lazy(cls, name: str, import_path: str) -> None:
        cls._lazy_backends[name] = import_path

    @classmethod
    def _resolve_backend(cls, name: str) -> type[Tracker]:
        if name in cls._backends:
            return cls._backends[name]
        if name not in cls._lazy_backends:
            available = ", ".join(cls.available()) or "(none)"
            msg = f"Unknown tracker backend {name!r}. Available: {available}"
            raise KeyError(msg)

        module_path, _, attr_name = cls._lazy_backends[name].partition(":")
        if not module_path or not attr_name:
            msg = f"Invalid lazy tracker path for {name!r}: {cls._lazy_backends[name]!r}"
            raise ValueError(msg)

        module = importlib.import_module(module_path)
        backend_cls = getattr(module, attr_name)
        if not isinstance(backend_cls, type) or not issubclass(backend_cls, Tracker):
            msg = f"Lazy tracker {name!r} did not resolve to a Tracker subclass."
            raise TypeError(msg)

        cls._backends[name] = backend_cls
        return backend_cls

    @classmethod
    def create(cls, name: str, settings: TrackingSettings) -> Tracker:
        return cls._resolve_backend(name)(settings)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(set(cls._backends) | set(cls._lazy_backends))
