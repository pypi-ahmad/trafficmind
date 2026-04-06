"""Reusable service-layer exceptions."""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for service-layer errors."""


class NotFoundError(ServiceError):
    """Raised when an entity cannot be found."""


class ConflictError(ServiceError):
    """Raised when a write conflicts with existing data or references."""


class ServiceValidationError(ServiceError):
    """Raised when a business validation fails."""