"""Deterministic stationary-object and dwell-time analysis.

This module is the core analysis layer.  It is pure — no DB access, no
side-effects — so that it can be called from both the rules engine and
from offline analytics pipelines.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime

from services.dwell.schemas import (
    DwellAnalysis,
    DwellOutcome,
    DwellThresholds,
    StationarityAssessment,
)
from services.tracking.schemas import TrackedObject, TrajectoryPoint

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_stationarity(
    trajectory: Sequence[TrajectoryPoint],
    *,
    stationary_speed_px: float = 2.0,
    lookback: int | None = None,
) -> StationarityAssessment:
    """Analyse a trajectory window for stationarity.

    Returns a pure motion summary that does NOT depend on zone context or
    dwell timing.  This lets callers decide independently whether the
    object is genuinely stopped.

    Args:
        trajectory: Ordered trajectory points.
        stationary_speed_px: Per-segment displacement below which a segment
            is counted as stationary.
        lookback: If set, only the last *lookback* points are analysed.
    """
    points = list(trajectory[-lookback:]) if lookback else list(trajectory)

    if len(points) < 2:
        return StationarityAssessment(
            samples_analyzed=len(points),
            stationary_samples=len(points),
            stationary_ratio=1.0,
            longest_stationary_streak_samples=len(points),
            net_displacement_px=0.0,
            is_currently_stationary=True,
        )

    segments = len(points) - 1
    speeds: list[float] = []
    stationary_flags: list[bool] = []

    for prev, curr in zip(points[:-1], points[1:], strict=False):
        dx = curr.point.x - prev.point.x
        dy = curr.point.y - prev.point.y
        speed = math.hypot(dx, dy)
        speeds.append(speed)
        stationary_flags.append(speed <= stationary_speed_px)

    stationary_count = sum(stationary_flags)
    stationary_ratio = stationary_count / segments if segments > 0 else 1.0

    # Longest contiguous stationary streak (in segments)
    longest_streak = 0
    current_streak = 0
    longest_streak_start = 0
    current_streak_start = 0
    for idx, is_stat in enumerate(stationary_flags):
        if is_stat:
            if current_streak == 0:
                current_streak_start = idx
            current_streak += 1
            if current_streak > longest_streak:
                longest_streak = current_streak
                longest_streak_start = current_streak_start
        else:
            current_streak = 0

    # Convert longest streak to seconds if timestamps available
    longest_streak_seconds: float | None = None
    if longest_streak > 0:
        streak_start_pt = points[longest_streak_start]
        streak_end_pt = points[longest_streak_start + longest_streak]
        if streak_start_pt.timestamp is not None and streak_end_pt.timestamp is not None:
            longest_streak_seconds = max(
                (streak_end_pt.timestamp - streak_start_pt.timestamp).total_seconds(),
                0.0,
            )

    current_speed_px = speeds[-1] if speeds else 0.0
    avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
    max_speed = max(speeds) if speeds else 0.0
    net_displacement = math.hypot(
        points[-1].point.x - points[0].point.x,
        points[-1].point.y - points[0].point.y,
    )

    return StationarityAssessment(
        samples_analyzed=segments,
        stationary_samples=stationary_count,
        stationary_ratio=round(stationary_ratio, 4),
        longest_stationary_streak_samples=longest_streak,
        longest_stationary_streak_seconds=(
            round(longest_streak_seconds, 3) if longest_streak_seconds is not None else None
        ),
        net_displacement_px=round(net_displacement, 3),
        current_speed_px=round(current_speed_px, 3),
        is_currently_stationary=stationary_flags[-1] if stationary_flags else True,
        average_speed_px=round(avg_speed, 3),
        max_speed_px=round(max_speed, 3),
    )


def analyze_dwell(
    track: TrackedObject,
    *,
    thresholds: DwellThresholds,
    entered_at: datetime | None = None,
    timestamp: datetime | None = None,
    zone_id: str | None = None,
    zone_name: str | None = None,
    zone_type: str | None = None,
    lookback: int | None = None,
    allow_track_lifetime_fallback: bool = True,
) -> DwellAnalysis:
    """Full dwell analysis for a tracked object in a zone.

    Combines stationarity assessment with zone/timing context to produce
    a deterministic outcome.  The result carries enough metadata for
    downstream rules or review UIs to explain the decision.

    Args:
        track: The tracked object being evaluated.
        thresholds: Scenario-specific thresholds (configurable per camera/zone).
        entered_at: When the track entered the zone (from engine occupancy).
        timestamp: Current evaluation timestamp.
        zone_id: Zone identifier for metadata.
        zone_name: Zone display name for metadata.
        lookback: Trajectory lookback window for stationarity analysis.
    """
    warnings: list[str] = []
    track_class = track.class_name.strip().casefold()
    included_classes = {name.strip().casefold() for name in thresholds.included_class_names}
    excluded_classes = {name.strip().casefold() for name in thresholds.excluded_class_names}

    # Category filter
    if track.category not in thresholds.applicable_categories:
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            reason=f"Object category {track.category.value!r} is not applicable for {thresholds.scenario.value}.",
        )

    if included_classes and track_class not in included_classes:
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            reason=(
                f"Object class {track.class_name!r} is not included for {thresholds.scenario.value}."
            ),
        )

    if track_class in excluded_classes:
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            reason=(
                f"Object class {track.class_name!r} is exempt from {thresholds.scenario.value}."
            ),
        )

    # Compute dwell duration
    dwell_seconds = _compute_dwell_seconds(
        track,
        entered_at,
        timestamp,
        allow_track_lifetime_fallback=allow_track_lifetime_fallback,
    )
    if dwell_seconds is None:
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            reason="Insufficient timing data to compute dwell duration.",
            warnings=[
                "No reliable zone-entry timing was available for dwell computation."
                if not allow_track_lifetime_fallback
                else "No entered_at, no track timestamps, and no evaluation timestamp."
            ],
        )

    # Stationarity assessment
    stationarity = assess_stationarity(
        track.trajectory,
        stationary_speed_px=thresholds.stationary_speed_px,
        lookback=lookback,
    )

    # Grace period
    if dwell_seconds <= thresholds.grace_period_seconds:
        return DwellAnalysis(
            outcome=DwellOutcome.GRACE_PERIOD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason=(
                f"Dwell of {dwell_seconds:.1f}s is within the"
                f" {thresholds.grace_period_seconds:.1f}s grace period."
            ),
        )

    # Stationarity ratio check — prevent naive triggers on brief pauses
    if stationarity.stationary_ratio < thresholds.min_stationary_ratio:
        warnings.append(
            f"Stationary ratio {stationarity.stationary_ratio:.2f}"
            f" is below the {thresholds.min_stationary_ratio:.2f} threshold;"
            f" object may be moving intermittently."
        )
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason=(
                f"Object is in zone for {dwell_seconds:.1f}s but stationary ratio"
                f" ({stationarity.stationary_ratio:.2f}) is insufficient."
            ),
            warnings=warnings,
        )

    # Minimum contiguous stationary streak check
    streak_ok = _streak_meets_minimum(stationarity, thresholds)
    if not streak_ok:
        warnings.append(
            f"Longest stationary streak does not meet the"
            f" {thresholds.min_stationary_streak_seconds:.1f}s minimum."
        )
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason="Object has paused but not continuously enough to qualify.",
            warnings=warnings,
        )

    # Check if currently stationary — don't flag a vehicle that just resumed motion
    if not stationarity.is_currently_stationary:
        warnings.append("Object was stationary but has now resumed motion.")
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason="Object was stationary but has resumed motion before the dwell threshold.",
            warnings=warnings,
        )

    if stationarity.net_displacement_px > thresholds.max_stationary_displacement_px:
        warnings.append(
            f"Net displacement {stationarity.net_displacement_px:.2f}px exceeds the "
            f"{thresholds.max_stationary_displacement_px:.2f}px stationary window; "
            "object appears to be creeping rather than truly stopped."
        )
        return DwellAnalysis(
            outcome=DwellOutcome.BELOW_THRESHOLD,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason="Object movement stays slow but drifts too far to count as stationary dwell.",
            warnings=warnings,
        )

    # Below dwell threshold — candidate but not yet violation
    if dwell_seconds < thresholds.max_dwell_seconds:
        return DwellAnalysis(
            outcome=DwellOutcome.CANDIDATE,
            scenario=thresholds.scenario,
            track_id=track.track_id,
            zone_id=zone_id,
            zone_name=zone_name,
            zone_type=zone_type,
            object_category=track.category,
            object_class=track.class_name,
            dwell_seconds=dwell_seconds,
            grace_period_seconds=thresholds.grace_period_seconds,
            threshold_seconds=thresholds.max_dwell_seconds,
            stationarity=stationarity,
            reason=(
                f"{track.class_name} {track.track_id} stationary for {dwell_seconds:.1f}s"
                f" (threshold: {thresholds.max_dwell_seconds:.1f}s); monitoring."
            ),
        )

    # Violation confirmed
    excess = dwell_seconds - thresholds.max_dwell_seconds
    return DwellAnalysis(
        outcome=DwellOutcome.VIOLATION,
        scenario=thresholds.scenario,
        track_id=track.track_id,
        zone_id=zone_id,
        zone_name=zone_name,
        zone_type=zone_type,
        object_category=track.category,
        object_class=track.class_name,
        dwell_seconds=dwell_seconds,
        grace_period_seconds=thresholds.grace_period_seconds,
        threshold_seconds=thresholds.max_dwell_seconds,
        threshold_exceeded_by=excess,
        stationarity=stationarity,
        reason=(
            f"{track.class_name} {track.track_id} stationary in"
            f" '{zone_name or zone_id}' for {dwell_seconds:.1f}s"
            f" (limit: {thresholds.max_dwell_seconds:.1f}s,"
            f" exceeded by {excess:.1f}s)."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_dwell_seconds(
    track: TrackedObject,
    entered_at: datetime | None,
    timestamp: datetime | None,
    *,
    allow_track_lifetime_fallback: bool,
) -> float | None:
    """Compute dwell duration from the best available timing data."""
    # Prefer explicit zone-entry timestamp
    if entered_at is not None and timestamp is not None:
        return max((timestamp - entered_at).total_seconds(), 0.0)
    if entered_at is not None and track.last_seen_at is not None:
        return max((track.last_seen_at - entered_at).total_seconds(), 0.0)
    if not allow_track_lifetime_fallback:
        return None
    # Fall back to full track lifetime if no zone-entry time
    if track.first_seen_at is not None and track.last_seen_at is not None:
        return max((track.last_seen_at - track.first_seen_at).total_seconds(), 0.0)
    if track.first_seen_at is not None and timestamp is not None:
        return max((timestamp - track.first_seen_at).total_seconds(), 0.0)
    return None


def _streak_meets_minimum(
    stationarity: StationarityAssessment,
    thresholds: DwellThresholds,
) -> bool:
    """Check whether the longest stationary streak meets the min duration."""
    if thresholds.min_stationary_streak_seconds <= 0:
        return True
    if stationarity.longest_stationary_streak_seconds is not None:
        return stationarity.longest_stationary_streak_seconds >= thresholds.min_stationary_streak_seconds
    # When timestamps are unavailable, fall back to sample count heuristic.
    # Assume ~10 fps as a conservative estimate.
    assumed_fps = 10.0
    estimated_seconds = stationarity.longest_stationary_streak_samples / assumed_fps
    return estimated_seconds >= thresholds.min_stationary_streak_seconds
