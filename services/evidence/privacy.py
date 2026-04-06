"""Privacy and redaction helpers for evidence manifests and exports."""

from __future__ import annotations

from copy import deepcopy

from services.evidence.schemas import (
    EvidenceAccessResolution,
    EvidenceAccessRole,
    EvidenceAsset,
    EvidenceAssetView,
    EvidenceManifestDocument,
    EvidencePrivacyPolicy,
)


def is_original_access_authorized(
    *,
    role: EvidenceAccessRole,
    policy: EvidencePrivacyPolicy,
) -> bool:
    return role in policy.authorized_original_roles


def resolve_access_resolution(
    *,
    policy: EvidencePrivacyPolicy,
    role: EvidenceAccessRole,
    requested_view: EvidenceAssetView | None,
    default_view: EvidenceAssetView | None = None,
) -> EvidenceAccessResolution:
    original_allowed = is_original_access_authorized(role=role, policy=policy)
    notes: list[str] = []
    if requested_view == EvidenceAssetView.ORIGINAL and not original_allowed:
        notes.append("Original evidence access is restricted; returning the redacted view instead.")

    if requested_view == EvidenceAssetView.ORIGINAL and original_allowed:
        resolved_view = EvidenceAssetView.ORIGINAL
    elif requested_view == EvidenceAssetView.REDACTED:
        resolved_view = EvidenceAssetView.REDACTED
    else:
        fallback_view = default_view or policy.default_asset_view
        if fallback_view == EvidenceAssetView.ORIGINAL and not original_allowed:
            resolved_view = EvidenceAssetView.REDACTED
            notes.append("Original evidence is not used as an implicit default for roles without original access.")
        else:
            resolved_view = fallback_view

    if resolved_view == EvidenceAssetView.REDACTED:
        notes.append("Redacted evidence is the default response for operator-facing and export-facing access paths.")

    return EvidenceAccessResolution(
        requested_role=role,
        requested_view=requested_view,
        resolved_view=resolved_view,
        original_access_authorized=original_allowed,
        resolution_notes=notes,
    )


def resolve_visible_assets(
    *,
    document: EvidenceManifestDocument,
    access: EvidenceAccessResolution,
) -> list[EvidenceAsset]:
    if access.resolved_view == EvidenceAssetView.ORIGINAL:
        return list(document.assets)
    if document.redacted_assets:
        return list(document.redacted_assets)
    return []


def sanitize_manifest_for_access(
    *,
    document: EvidenceManifestDocument,
    access: EvidenceAccessResolution,
) -> EvidenceManifestDocument:
    visible_assets = resolve_visible_assets(document=document, access=access)
    payload = deepcopy(document.model_dump(mode="json"))
    payload["assets"] = [asset.model_dump(mode="json") for asset in visible_assets]
    payload["active_asset_view"] = access.resolved_view.value
    if access.resolved_view == EvidenceAssetView.REDACTED and not access.original_access_authorized:
        payload["audit"] = {
            **payload.get("audit", {}),
            "restricted_original_assets": True,
        }
    return EvidenceManifestDocument.model_validate(payload)


def mask_plate_text(value: str | None) -> str | None:
    if value is None:
        return None

    alnum_positions = [index for index, char in enumerate(value) if char.isalnum()]
    if not alnum_positions:
        return value

    visible_positions = set(alnum_positions[:2] + alnum_positions[-2:])
    masked_chars: list[str] = []
    for index, char in enumerate(value):
        if char.isalnum() and index not in visible_positions:
            masked_chars.append("*")
        else:
            masked_chars.append(char)
    return "".join(masked_chars)