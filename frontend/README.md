This frontend now serves as the TrafficMind operations console foundation.

## Current routes

- `/` — spatial operations dashboard with camera and junction map markers, hotspot summaries, analytics-backed location incident rollups, and selection-linked navigation
- `/cameras/[cameraId]` — camera detail page wired to the existing FastAPI camera detail endpoint
- `/evaluation` — benchmark and evaluation summary view grounded in fixture-derived reports and optional stored local artifacts
- `/events` — event feed filter foundation that preserves camera and junction context even while the backend feed endpoints are still scaffolded

## Configuration

The dashboard reads live camera metadata from the FastAPI backend.

- `TRAFFICMIND_API_BASE_URL` or `NEXT_PUBLIC_TRAFFICMIND_API_BASE_URL`
	Default: `http://127.0.0.1:8000/api/v1`
	Legacy fallback: `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_MAP_PROVIDER`
	Supported values: `coordinate-grid` (default), `maplibre`
- `NEXT_PUBLIC_MAP_STYLE_URL`
	Required only when `NEXT_PUBLIC_MAP_PROVIDER=maplibre`
- `NEXT_PUBLIC_MAP_ACCESS_TOKEN`
	Optional token passthrough for future provider needs
- `TRAFFICMIND_SPATIAL_LOOKBACK_DAYS` or `NEXT_PUBLIC_TRAFFICMIND_SPATIAL_LOOKBACK_DAYS`
	Default: `7`
- `TRAFFICMIND_SPATIAL_TOP_N` or `NEXT_PUBLIC_TRAFFICMIND_SPATIAL_TOP_N`
	Default: `48`

If no basemap style is configured, the dashboard uses an honest coordinate-grid fallback based on real camera latitude and longitude values. It does not fake street-map precision.

## Getting Started

Run the development server from the `frontend/` directory:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser.

For the dashboard to populate live camera metadata, make sure the API is running on the configured base URL.

If you want a commit-safe template first, render one from the repo root with `python infra/scripts/render_env.py --profile local --output .env`.

## Backend availability notes

- Cameras: implemented and used live by the dashboard
- Evaluation summaries: implemented and used live by `/evaluation` through `GET /analytics/evaluation` for fixture-backed and stored-artifact-backed results
- Hotspot analytics: implemented and used live by the dashboard through `POST /analytics/hotspots` for persisted violations and watchlist alerts
- Events: scaffolded in the API, currently returns `501 Not Implemented`
- Violations: scaffolded in the API, currently returns `501 Not Implemented`

The dashboard reflects those gaps explicitly in the UI rather than inventing incident counts or benchmark metadata. The map can show real location summaries from hotspot analytics even while the raw `/events` and `/violations` feed routes remain scaffolded, and the evaluation page only shows manual notes or version filters when local artifacts explicitly provide them.

## Evaluation workflow

The evaluation page is backed by the fixture-driven benchmarking foundation in the Python services layer.

- Default measured source: `tests/fixtures/evaluation/benchmark_suite.json`
- Optional stored artifact directory: configured by the backend `evaluation_artifact_dir` setting

To create a stored artifact that the UI can discover, run the evaluation CLI with an output path from the repository root:

```bash
python -m services.evaluation tests/fixtures/evaluation/benchmark_suite.json --output outputs/evaluation/fixture-baseline.json --artifact-label fixture-baseline
```

See `docs/evaluation.md` for the full workflow and interpretation guidance.

## Operations view model

- Camera markers use exact backend latitude/longitude when present.
- Junction markers are derived from shared `location_name` values today, which keeps grouping honest until a dedicated intersection entity exists.
- Hotspot cards and top-location cards link back into the same dashboard selection, camera detail route, and event feed filter route so operators can move between views without losing context.
- When hotspot analytics is unavailable, the dashboard falls back to camera status and map-coverage signals instead of pretending it has live incident intelligence.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs)
- [Learn Next.js](https://nextjs.org/learn)

## Deploy

This app can be deployed like any standard Next.js project once the environment variables above are configured for the target API and map provider.
