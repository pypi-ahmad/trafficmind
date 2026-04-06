"""Local development entrypoint for the workflow service."""

from __future__ import annotations

import uvicorn

from apps.workflow.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "apps.workflow.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()