# Motion Analytics Service (`services/motion/`)

Calibration-aware speed estimation and directional analytics for tracked road users.

This module is intentionally separate from `services/tracking/`:

- `services/tracking/` owns per-camera object continuity and pixel-space motion.
- `services/motion/` converts track history into speed and travel-direction analytics.

## Design Goals

- Use track history plus timestamps when available.
- Make calibration-awareness explicit instead of hiding it in generic camera JSON.
- Keep outputs useful even without full calibration.
- Stay conservative about enforcement claims.

## Estimate Tiers

The module produces one of three estimate tiers:

- `rough`: no physical calibration, so speed is reported in `px/s` or `px/frame`.
- `approximate`: a linear `meters_per_pixel` scale exists, so speed can be reported in physical units, but it is still an approximation.
- `calibrated`: a ground-plane homography exists, so physical distance comes from the calibrated transform.

Even calibrated estimates are **not** treated as enforcement-grade unless the calibration profile explicitly says it has been validated for that purpose.

## Calibration Contract

Camera `calibration_config` may include a motion payload like this:

```json
{
  "motion": {
    "mode": "scale_approximation",
    "scale": {
      "meters_per_pixel": 0.08,
      "source_note": "Approximate lane-width based scale"
    },
    "direction": {
      "scene_direction_map": {
        "east": "northbound",
        "west": "southbound"
      },
      "inbound_vector": {"dx": 1.0, "dy": 0.0},
      "lane_direction_vector": {"dx": 1.0, "dy": 0.0},
      "lane_name": "through-lane-a"
    },
    "enforcement_validated": false,
    "notes": "Use for analytics and candidate screening only"
  }
}
```

For calibrated ground-plane estimates, replace `scale` with:

```json
{
  "mode": "planar_homography",
  "homography": {
    "homography_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "meters_per_world_unit": 0.05
  }
}
```

## Outputs

`estimate_track_motion(...)` returns:

- estimated speed
- speed unit
- estimate tier (`rough`, `approximate`, `calibrated`)
- reliability band and score
- heading / direction vector
- scene direction label (for example `northbound`)
- inbound/outbound classification
- lane-relative direction (`with_flow`, `against_flow`, `cross_traffic`)

Helpers are provided for:

- analytics payload generation via `MotionAnalytics.to_summary_dict()`
- overspeed screening via `detect_overspeed_candidate(...)`
- wrong-way screening via `detect_wrong_way_candidate(...)`

## Assumptions and Limitations

- Pixel-only estimates are useful for trend analytics, not physical enforcement.
- Approximate scale estimates are better than pixel-only, but still depend on scene depth and perspective assumptions.
- A homography improves physical distance estimation, but enforcement claims still require validated calibration workflows and operational controls outside this module.
- Overspeed and wrong-way outputs are candidate screens. They should feed review or rules workflows, not bypass them.

## Running tests

```bash
.\.venv\Scripts\python -m pytest tests/motion -q
```