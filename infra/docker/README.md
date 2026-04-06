# Docker Assets

Place Dockerfiles, compose assets, and container-specific runtime configuration here.

Keep these assets local-first and developer-friendly before introducing environment-specific deployment overlays.

Current status:

- No Dockerfiles or compose files are shipped yet.
- That is intentional. The repository now has env profiles, readiness probes, and CI validation, but it still does not claim containerized production readiness.
- Add container assets here only when they are tested end to end and reflect real supported service startup paths.
