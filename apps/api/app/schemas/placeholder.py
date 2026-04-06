"""Typed placeholder responses for scaffolded endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NotImplementedResponse(BaseModel):
    """Explicit response for foundation routes that are not implemented yet."""

    status: Literal["not_implemented"] = "not_implemented"
    resource: str
    detail: str