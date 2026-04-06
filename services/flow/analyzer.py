"""Practical lane occupancy and queue analytics."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise

from services.dwell import assess_stationarity
from services.flow.schemas import (
    CongestionLevel,
    LaneAnalytics,
    LaneAnalyticsLaneConfig,
    LaneObservation,
    LaneOccupancyMetrics,
    LaneQueueMetrics,
    QueueAnchorSource,
    QueuedTrack,
)
from services.tracking.schemas import Point2D, TrackedObject, TrackingResult
from services.tracking.utils import point_in_polygon


def analyze_lane_snapshot(
    lane: LaneAnalyticsLaneConfig,
    tracks: Sequence[TrackedObject],
    *,
    timestamp: datetime,
    history: Sequence[LaneObservation] = (),
    queue_started_at: datetime | None = None,
) -> tuple[LaneAnalytics, LaneObservation, datetime | None]:
    """Analyze one lane for one frame with optional history."""

    warnings: list[str] = []
    assumptions = [
        "Queue extent is reported in pixels from a configured stop-line or queue anchor.",
        "Occupancy ratio is the time-weighted fraction of the rolling window "
        "during which at least one tracked object occupied the lane polygon "
        "(temporal occupancy, not spatial coverage).",
        "Queue duration seconds is the elapsed time for the current "
        "uninterrupted queue episode and resets when the queue breaks.",
        "Utilization ratio, when available, is average_active_track_count "
        "divided by nominal_capacity_count and should be treated as a "
        "lane-load heuristic rather than an engineering saturation or "
        "level-of-service metric.",
        "Congestion level is a threshold bucket derived from occupancy and "
        "queue persistence, not a travel-time, delay, or "
        "signal-optimization metric.",
        "Queue is vetoed when the closest track to the anchor is moving "
        "freely, indicating intersection flow.",
    ]

    relevant_tracks = [
        track for track in tracks
        if track.category in lane.included_categories
        and point_in_polygon(track.centroid, lane.lane_polygon)
    ]
    active_track_ids = [track.track_id for track in relevant_tracks]
    occupied = bool(relevant_tracks)

    queue_metrics, queue_detected, queue_started_at, queue_warnings = _queue_metrics(
        lane,
        relevant_tracks,
        timestamp=timestamp,
        queue_started_at=queue_started_at,
    )
    warnings.extend(queue_warnings)

    observation = LaneObservation(
        observed_at=timestamp,
        active_track_count=len(relevant_tracks),
        occupied=occupied,
        queue_detected=queue_detected,
        queue_track_count=queue_metrics.queue_track_count,
        queue_extent_px=queue_metrics.queue_extent_px,
    )
    window = [*history, observation]
    occupancy_metrics = _occupancy_metrics(lane, window, active_track_ids)
    queue_metrics = _finalize_queue_window_metrics(queue_metrics, window)
    congestion_level = _congestion_level(lane, occupancy_metrics, queue_metrics)

    if lane.nominal_capacity_count is None:
        warnings.append(
            "Utilization ratio is unavailable until nominal_capacity_count is "
            "configured for the lane."
        )
    if occupancy_metrics.window_seconds + 1e-9 < lane.window_seconds:
        warnings.append(
            "Rolling window is still warming up; windowed metrics currently cover "
            f"{occupancy_metrics.window_seconds:.1f}s of the configured "
            f"{lane.window_seconds:.1f}s window."
        )

    return (
        LaneAnalytics(
            lane_id=lane.lane_id,
            lane_name=lane.lane_name,
            observed_at=timestamp,
            congestion_level=congestion_level,
            occupancy=occupancy_metrics,
            queue=queue_metrics,
            assumptions=assumptions,
            warnings=warnings,
        ),
        observation,
        queue_started_at,
    )


class LaneAnalyticsEngine:
    """Small stateful engine for rolling lane analytics windows."""

    def __init__(self, lanes: Sequence[LaneAnalyticsLaneConfig]) -> None:
        self._lanes = {lane.lane_id: lane for lane in lanes}
        self._history: dict[str, deque[LaneObservation]] = {
            lane_id: deque() for lane_id in self._lanes
        }
        self._queue_started_at: dict[str, datetime | None] = {
            lane_id: None for lane_id in self._lanes
        }

    @property
    def lanes(self) -> list[LaneAnalyticsLaneConfig]:
        return list(self._lanes.values())

    def reset(self) -> None:
        for history in self._history.values():
            history.clear()
        for lane_id in self._queue_started_at:
            self._queue_started_at[lane_id] = None

    def evaluate(self, tracking_result: TrackingResult) -> list[LaneAnalytics]:
        timestamp = tracking_result.timestamp or datetime.now(UTC)
        results: list[LaneAnalytics] = []
        for lane_id, lane in self._lanes.items():
            history = self._trimmed_history(lane_id, timestamp, lane.window_seconds)
            analytics, observation, queue_started_at = analyze_lane_snapshot(
                lane,
                tracking_result.tracks,
                timestamp=timestamp,
                history=history,
                queue_started_at=self._queue_started_at[lane_id],
            )
            history.append(observation)
            self._queue_started_at[lane_id] = queue_started_at
            results.append(analytics)
        return results

    def _trimmed_history(
        self,
        lane_id: str,
        timestamp: datetime,
        window_seconds: float,
    ) -> deque[LaneObservation]:
        history = self._history[lane_id]
        cutoff = timestamp.timestamp() - window_seconds
        while history and history[0].observed_at.timestamp() < cutoff:
            history.popleft()
        return history


def _queue_metrics(
    lane: LaneAnalyticsLaneConfig,
    tracks: Sequence[TrackedObject],
    *,
    timestamp: datetime,
    queue_started_at: datetime | None,
) -> tuple[LaneQueueMetrics, bool, datetime | None, list[str]]:
    warnings: list[str] = []
    anchor, anchor_source = _queue_anchor(lane)
    if anchor is None:
        warnings.append(
            "Queue analytics require a stop-line or queue_reference_point; "
            "queue metrics are disabled for this lane."
        )
        return LaneQueueMetrics(anchor_source=QueueAnchorSource.NONE), False, None, warnings

    ordered = []
    for track in tracks:
        stationarity = assess_stationarity(
            track.trajectory,
            stationary_speed_px=lane.stationary_speed_px,
            lookback=lane.stationarity_lookback_points,
        )
        ordered.append((
            _distance(track.centroid, anchor),
            track,
            stationarity,
        ))
    ordered.sort(key=lambda item: item[0])

    nearest_in_radius = next(
        (
            (distance, track, stationarity)
            for distance, track, stationarity in ordered
            if distance <= lane.queue_anchor_radius_px
        ),
        None,
    )
    if nearest_in_radius is not None and not _is_track_queued_candidate(
        nearest_in_radius[2], lane,
    ):
        queue_detected = False
        queue_started_at = None
        return (
            LaneQueueMetrics(anchor_source=anchor_source),
            queue_detected,
            queue_started_at,
            warnings,
        )

    queue_members: list[QueuedTrack] = []
    previous_distance: float | None = None
    started = False
    for distance, track, stationarity in ordered:
        if not started:
            if distance > lane.queue_anchor_radius_px:
                break
            if not _is_track_queued_candidate(stationarity, lane):
                continue
            started = True
        else:
            if (
                previous_distance is not None
                and (distance - previous_distance) > lane.max_queue_gap_px
            ):
                break
            if not _is_track_queued_candidate(stationarity, lane):
                break

        queue_members.append(
            QueuedTrack(
                track_id=track.track_id,
                class_name=track.class_name,
                anchor_distance_px=round(distance, 3),
                stationary_ratio=stationarity.stationary_ratio,
                current_speed_px=stationarity.current_speed_px,
            )
        )
        previous_distance = distance

    queue_detected = len(queue_members) >= lane.min_queue_count
    if queue_detected:
        queue_started_at = queue_started_at or timestamp
        queue_duration_seconds = max((timestamp - queue_started_at).total_seconds(), 0.0)
    else:
        queue_started_at = None
        queue_duration_seconds = 0.0

    queue_extent_px = queue_members[-1].anchor_distance_px if queue_members else 0.0
    return (
        LaneQueueMetrics(
            anchor_source=anchor_source,
            queue_detected=queue_detected,
            queue_track_count=len(queue_members),
            queue_extent_px=queue_extent_px,
            queue_duration_seconds=queue_duration_seconds,
            queued_track_ids=[member.track_id for member in queue_members],
            queued_tracks=queue_members,
        ),
        queue_detected,
        queue_started_at,
        warnings,
    )


def _occupancy_metrics(
    lane: LaneAnalyticsLaneConfig,
    window: Sequence[LaneObservation],
    active_track_ids: list[str],
) -> LaneOccupancyMetrics:
    occupancy_ratio = _time_weighted_average(
        window,
        selector=lambda obs: 1.0 if obs.occupied else 0.0,
    )
    avg_active_count = _time_weighted_average(
        window,
        selector=lambda obs: float(obs.active_track_count),
    )
    peak_active_count = max((obs.active_track_count for obs in window), default=0)
    window_seconds = _observed_window_seconds(window)

    utilization_ratio: float | None = None
    if lane.nominal_capacity_count is not None:
        utilization_ratio = round(avg_active_count / lane.nominal_capacity_count, 3)

    current = window[-1]
    return LaneOccupancyMetrics(
        active_track_count=current.active_track_count,
        active_track_ids=active_track_ids,
        occupied=current.occupied,
        occupancy_ratio=round(occupancy_ratio, 3),
        average_active_track_count=round(avg_active_count, 3),
        peak_active_track_count=peak_active_count,
        utilization_ratio=utilization_ratio,
        window_seconds=round(window_seconds, 3),
    )


def _finalize_queue_window_metrics(
    queue_metrics: LaneQueueMetrics,
    window: Sequence[LaneObservation],
) -> LaneQueueMetrics:
    avg_queue_count = _time_weighted_average(
        window,
        selector=lambda obs: float(obs.queue_track_count),
    )
    peak_queue_count = max((obs.queue_track_count for obs in window), default=0)
    return queue_metrics.model_copy(
        update={
            "average_queue_track_count": round(avg_queue_count, 3),
            "peak_queue_track_count": peak_queue_count,
        }
    )


def _congestion_level(
    lane: LaneAnalyticsLaneConfig,
    occupancy: LaneOccupancyMetrics,
    queue: LaneQueueMetrics,
) -> CongestionLevel:
    if queue.queue_detected and (
        queue.queue_duration_seconds >= lane.congestion_queue_duration_seconds
        or queue.queue_track_count >= lane.saturation_queue_count
        or (occupancy.utilization_ratio is not None and occupancy.utilization_ratio >= 1.0)
    ):
        return CongestionLevel.CONGESTED
    if (
        occupancy.occupancy_ratio >= lane.congestion_occupancy_ratio
        and occupancy.window_seconds > 0.0
    ):
        return CongestionLevel.CONGESTED
    if queue.queue_detected:
        return CongestionLevel.QUEUED
    if occupancy.occupancy_ratio >= lane.heavy_occupancy_ratio:
        return CongestionLevel.HEAVY
    return CongestionLevel.FREE_FLOW


def _queue_anchor(lane: LaneAnalyticsLaneConfig) -> tuple[Point2D | None, QueueAnchorSource]:
    if lane.queue_reference_point is not None:
        return lane.queue_reference_point, QueueAnchorSource.REFERENCE_POINT
    if lane.stop_line is not None:
        return Point2D(
            x=(lane.stop_line.start.x + lane.stop_line.end.x) / 2,
            y=(lane.stop_line.start.y + lane.stop_line.end.y) / 2,
        ), QueueAnchorSource.STOP_LINE
    return None, QueueAnchorSource.NONE


def _is_track_queued_candidate(stationarity: object, lane: LaneAnalyticsLaneConfig) -> bool:
    return bool(
        getattr(stationarity, "is_currently_stationary", False)
        and getattr(stationarity, "stationary_ratio", 0.0) >= lane.min_stationary_ratio
    )


def _observed_window_seconds(window: Sequence[LaneObservation]) -> float:
    if len(window) < 2:
        return 0.0
    return max((window[-1].observed_at - window[0].observed_at).total_seconds(), 0.0)


def _time_weighted_average(
    window: Sequence[LaneObservation],
    *,
    selector,
) -> float:
    if not window:
        return 0.0
    if len(window) == 1:
        return float(selector(window[0]))

    total = 0.0
    covered = 0.0
    for current, following in pairwise(window):
        interval = max((following.observed_at - current.observed_at).total_seconds(), 0.0)
        total += float(selector(current)) * interval
        covered += interval
    if covered <= 0.0:
        return float(selector(window[-1]))
    return total / covered


def _distance(a: Point2D, b: Point2D) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)
