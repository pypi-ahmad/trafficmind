"""Logging configuration for the workflow service."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure process-wide logging once."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=False,
    )

    for noisy in ("uvicorn.access", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)