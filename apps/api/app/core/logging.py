"""Structured logging setup."""

from __future__ import annotations

import logging
import logging.config

from apps.api.app.core.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure process logging without mutating handlers ad hoc in lifespan."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn.access": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
            },
        }
    )
