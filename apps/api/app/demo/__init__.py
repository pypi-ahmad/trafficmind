"""Synthetic demo dataset helpers for local development and showcasing."""

from __future__ import annotations

from typing import Any

__all__ = ["DemoSeedResult", "list_demo_scenarios", "seed_demo_scenario"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from apps.api.app.demo import seed as _seed

        return getattr(_seed, name)
    raise AttributeError(name)
