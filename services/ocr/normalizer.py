"""Plate text normalisation utilities.

This module is the single place where raw OCR output is cleaned and
canonicalised before persistence.  It is deliberately **not** hard-coded
to one national plate format — the ``normalize_plate_text`` function
applies universal cleaning first, then optionally dispatches to a
country-specific formatter.

Country-specific formatters are registered in ``_COUNTRY_FORMATTERS``.
To add a new country, write a ``(str) -> str`` function and add it to
the dict keyed by its ISO 3166-1 alpha-2 code.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

_PLATE_CHAR_PREFIXES = {"L", "N"}


# ---------------------------------------------------------------------------
# Universal cleaner
# ---------------------------------------------------------------------------

def normalize_plate_text(
    raw_text: str,
    *,
    country_code: str | None = None,
) -> str:
    """Clean and normalise a raw OCR plate string.

    Steps
    -----
    1. Unicode NFKC normalisation (fullwidth → ASCII, etc.).
    2. Uppercase.
    3. Strip whitespace, hyphens, dots, and other punctuation.
    4. Remove characters that never appear on plates.
    5. If *country_code* has a registered formatter, apply it.

    Parameters
    ----------
    raw_text:
        Raw text straight from the OCR engine.
    country_code:
        Optional ISO 3166-1 alpha-2 hint (e.g. ``"SA"``, ``"US"``).
        When provided **and** a country formatter exists, it is applied
        after universal cleaning.

    Returns
    -------
    str
        Cleaned plate text, or empty string if nothing survived.
    """
    text = unicodedata.normalize("NFKC", raw_text)
    text = text.upper()
    text = _strip_non_plate_characters(text)

    if not text:
        return ""

    if country_code and country_code.upper() in _COUNTRY_FORMATTERS:
        text = _COUNTRY_FORMATTERS[country_code.upper()](text)

    return text


# ---------------------------------------------------------------------------
# Country-specific formatters
# ---------------------------------------------------------------------------

def _format_sa(text: str) -> str:
    """Saudi Arabia plates: up to 4 digits + up to 3 Arabic/Latin letters."""
    return text


def _format_ae(text: str) -> str:
    """UAE plates: variable by emirate — pass through for now."""
    return text


def _format_us(text: str) -> str:
    """US plates: highly variable by state — pass through for now."""
    return text


_COUNTRY_FORMATTERS: dict[str, Callable[[str], str]] = {
    "SA": _format_sa,
    "AE": _format_ae,
    "US": _format_us,
}


def register_country_formatter(
    country_code: str,
    formatter: Callable[[str], str],
) -> None:
    """Register a custom plate formatter for a country code."""
    normalized_code = country_code.strip().upper()
    if not normalized_code:
        msg = "country_code must not be blank"
        raise ValueError(msg)
    _COUNTRY_FORMATTERS[normalized_code] = formatter


def _strip_non_plate_characters(text: str) -> str:
    """Keep only unicode letters and numbers, canonicalizing digits to ASCII."""
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category == "Nd":
            cleaned.append(str(unicodedata.digit(char)))
            continue
        if category[:1] in _PLATE_CHAR_PREFIXES:
            cleaned.append(char)
    return "".join(cleaned)
