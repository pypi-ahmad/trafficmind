"""Tests for the privacy masking and evidence redaction foundation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from services.evidence.privacy import (
    is_original_access_authorized,
    mask_plate_text,
    resolve_access_resolution,
    resolve_visible_assets,
    sanitize_manifest_for_access,
)
from services.evidence.schemas import (
    EvidenceAccessResolution,
    EvidenceAccessRole,
    EvidenceAsset,
    EvidenceAssetKind,
    EvidenceAssetView,
    EvidenceClipWindow,
    EvidenceManifestDocument,
    EvidencePrivacyPolicy,
    EvidenceRedactionStatus,
    EvidenceRedactionTarget,
    EvidenceSelectionPolicy,
    EvidenceStorageState,
    EvidenceSubjectRef,
    EvidenceTimeline,
)

from apps.api.app.db.enums import EvidenceSubjectKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
_CAMERA_ID = uuid.uuid4()
_SUBJECT_ID = uuid.uuid4()


def _make_subject() -> EvidenceSubjectRef:
    return EvidenceSubjectRef(
        kind=EvidenceSubjectKind.VIOLATION_EVENT,
        subject_id=_SUBJECT_ID,
        camera_id=_CAMERA_ID,
        camera_code="CAM-PRIV-001",
        occurred_at=_NOW,
        plate_text="ABC1234",
    )


def _make_original_asset(kind: EvidenceAssetKind = EvidenceAssetKind.KEY_FRAME_SNAPSHOT) -> EvidenceAsset:
    return EvidenceAsset(
        asset_kind=kind,
        label="original_key_frame",
        asset_key=f"evidence/{kind.value}.jpg",
        asset_view=EvidenceAssetView.ORIGINAL,
        uri=f"s3://bucket/{kind.value}.jpg",
        storage_state=EvidenceStorageState.AVAILABLE,
        available=True,
        content_type="image/jpeg",
        frame_index=42,
        redaction_status=EvidenceRedactionStatus.NOT_REQUIRED,
        redaction_targets=[EvidenceRedactionTarget.FACE, EvidenceRedactionTarget.LICENSE_PLATE],
    )


def _make_redacted_asset(kind: EvidenceAssetKind = EvidenceAssetKind.KEY_FRAME_SNAPSHOT) -> EvidenceAsset:
    return EvidenceAsset(
        asset_kind=kind,
        label="redacted_key_frame",
        asset_key=f"evidence/{kind.value}_redacted.jpg",
        asset_view=EvidenceAssetView.REDACTED,
        uri=f"evidence/{kind.value}_redacted.jpg",
        storage_state=EvidenceStorageState.PLANNED,
        available=False,
        content_type="image/jpeg",
        frame_index=42,
        derived_from_asset_key=f"evidence/{kind.value}.jpg",
        redaction_status=EvidenceRedactionStatus.PLANNED,
        redaction_targets=[EvidenceRedactionTarget.FACE, EvidenceRedactionTarget.LICENSE_PLATE],
    )


def _make_document(
    *,
    include_redacted: bool = True,
) -> EvidenceManifestDocument:
    orig = _make_original_asset()
    redacted = _make_redacted_asset() if include_redacted else None
    return EvidenceManifestDocument(
        subject=_make_subject(),
        storage_namespace="evidence",
        selection_policy=EvidenceSelectionPolicy(
            event_frame_index=42,
            selection_reason="test_selection",
        ),
        timeline=EvidenceTimeline(
            occurred_at=_NOW,
            event_frame_index=42,
            clip_window=EvidenceClipWindow(),
        ),
        assets=[orig],
        redacted_assets=[redacted] if redacted else [],
        active_asset_view=EvidenceAssetView.ORIGINAL,
        original_asset_count=1,
        redacted_asset_count=1 if redacted else 0,
    )


# ===========================================================================
# is_original_access_authorized
# ===========================================================================


class TestIsOriginalAccessAuthorized:
    def test_privacy_officer_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.PRIVACY_OFFICER, policy=policy) is True

    def test_evidence_admin_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.EVIDENCE_ADMIN, policy=policy) is True

    def test_operator_not_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.OPERATOR, policy=policy) is False

    def test_reviewer_not_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.REVIEWER, policy=policy) is False

    def test_supervisor_not_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.SUPERVISOR, policy=policy) is False

    def test_export_service_not_authorized(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert is_original_access_authorized(role=EvidenceAccessRole.EXPORT_SERVICE, policy=policy) is False


# ===========================================================================
# resolve_access_resolution
# ===========================================================================


class TestResolveAccessResolution:
    def test_operator_defaults_to_redacted(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.OPERATOR,
            requested_view=None,
        )
        assert access.resolved_view == EvidenceAssetView.REDACTED
        assert access.original_access_authorized is False
        assert len(access.resolution_notes) > 0

    def test_operator_requesting_original_gets_redacted(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.OPERATOR,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        assert access.resolved_view == EvidenceAssetView.REDACTED
        assert access.original_access_authorized is False
        assert any("restricted" in note.lower() for note in access.resolution_notes)

    def test_privacy_officer_gets_original_when_requested(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.PRIVACY_OFFICER,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        assert access.resolved_view == EvidenceAssetView.ORIGINAL
        assert access.original_access_authorized is True

    def test_evidence_admin_gets_original_when_requested(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.EVIDENCE_ADMIN,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        assert access.resolved_view == EvidenceAssetView.ORIGINAL
        assert access.original_access_authorized is True

    def test_privacy_officer_requesting_redacted_gets_redacted(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.PRIVACY_OFFICER,
            requested_view=EvidenceAssetView.REDACTED,
        )
        assert access.resolved_view == EvidenceAssetView.REDACTED
        assert access.original_access_authorized is True

    def test_evidence_admin_default_view_is_redacted(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.EVIDENCE_ADMIN,
            requested_view=None,
        )
        assert access.resolved_view == EvidenceAssetView.REDACTED

    def test_resolution_preserves_requested_role(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.SUPERVISOR,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        assert access.requested_role == EvidenceAccessRole.SUPERVISOR
        assert access.requested_view == EvidenceAssetView.ORIGINAL

    def test_original_default_view_is_downgraded_for_unauthorized_role(self) -> None:
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.EXPORT_SERVICE,
            requested_view=None,
            default_view=EvidenceAssetView.ORIGINAL,
        )
        assert access.resolved_view == EvidenceAssetView.REDACTED
        assert access.original_access_authorized is False
        assert any("implicit default" in note.lower() for note in access.resolution_notes)


# ===========================================================================
# resolve_visible_assets
# ===========================================================================


class TestResolveVisibleAssets:
    def test_original_view_returns_original_assets(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.ORIGINAL,
            original_access_authorized=True,
        )
        visible = resolve_visible_assets(document=document, access=access)
        assert len(visible) == 1
        assert visible[0].asset_view == EvidenceAssetView.ORIGINAL

    def test_redacted_view_returns_redacted_assets(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=False,
        )
        visible = resolve_visible_assets(document=document, access=access)
        assert len(visible) == 1
        assert visible[0].asset_view == EvidenceAssetView.REDACTED

    def test_redacted_view_with_no_redacted_assets_returns_empty(self) -> None:
        document = _make_document(include_redacted=False)
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=False,
        )
        visible = resolve_visible_assets(document=document, access=access)
        assert visible == []


# ===========================================================================
# sanitize_manifest_for_access
# ===========================================================================


class TestSanitizeManifestForAccess:
    def test_redacted_access_replaces_assets_with_redacted(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=False,
        )
        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.active_asset_view == EvidenceAssetView.REDACTED
        assert len(sanitized.assets) == 1
        assert sanitized.assets[0].asset_view == EvidenceAssetView.REDACTED

    def test_redacted_access_marks_restricted_in_audit(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=False,
        )
        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.audit.get("restricted_original_assets") is True

    def test_original_access_keeps_original_assets(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.ORIGINAL,
            original_access_authorized=True,
        )
        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.active_asset_view == EvidenceAssetView.ORIGINAL
        assert len(sanitized.assets) == 1
        assert sanitized.assets[0].asset_view == EvidenceAssetView.ORIGINAL

    def test_authorized_redacted_does_not_mark_restricted(self) -> None:
        document = _make_document()
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=True,
        )
        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.audit.get("restricted_original_assets") is not True

    def test_sanitize_does_not_mutate_original(self) -> None:
        document = _make_document()
        original_asset_count = len(document.assets)
        access = EvidenceAccessResolution(
            resolved_view=EvidenceAssetView.REDACTED,
            original_access_authorized=False,
        )
        sanitize_manifest_for_access(document=document, access=access)
        assert len(document.assets) == original_asset_count
        assert document.assets[0].asset_view == EvidenceAssetView.ORIGINAL


# ===========================================================================
# mask_plate_text
# ===========================================================================


class TestMaskPlateText:
    def test_none_returns_none(self) -> None:
        assert mask_plate_text(None) is None

    def test_short_plate_preserves_all(self) -> None:
        assert mask_plate_text("AB") == "AB"
        assert mask_plate_text("ABC") == "ABC"
        assert mask_plate_text("ABCD") == "ABCD"

    def test_standard_plate_masks_middle(self) -> None:
        result = mask_plate_text("ABC1234")
        assert result is not None
        assert result[0:2] == "AB"
        assert result[-2:] == "34"
        assert "*" in result

    def test_preserves_non_alnum_characters(self) -> None:
        result = mask_plate_text("AB-C12-34")
        assert result is not None
        assert "-" in result

    def test_empty_string_returns_empty(self) -> None:
        assert mask_plate_text("") == ""

    def test_all_special_characters_unchanged(self) -> None:
        assert mask_plate_text("---") == "---"

    def test_long_plate_masks_interior(self) -> None:
        result = mask_plate_text("ABCDEFGH")
        assert result is not None
        assert result.startswith("AB")
        assert result.endswith("GH")
        assert result.count("*") == 4

    def test_single_char_stays_visible(self) -> None:
        assert mask_plate_text("A") == "A"


# ===========================================================================
# EvidencePrivacyPolicy defaults
# ===========================================================================


class TestEvidencePrivacyPolicyDefaults:
    def test_default_views_are_redacted(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert policy.default_asset_view == EvidenceAssetView.REDACTED
        assert policy.default_export_view == EvidenceAssetView.REDACTED

    def test_preserve_originals_by_default(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert policy.preserve_original_assets is True

    def test_authorized_roles_are_limited(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert set(policy.authorized_original_roles) == {
            EvidenceAccessRole.PRIVACY_OFFICER,
            EvidenceAccessRole.EVIDENCE_ADMIN,
        }

    def test_mask_by_default_roles(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert EvidenceAccessRole.OPERATOR in policy.mask_by_default_roles
        assert EvidenceAccessRole.REVIEWER in policy.mask_by_default_roles
        assert EvidenceAccessRole.SUPERVISOR in policy.mask_by_default_roles
        assert EvidenceAccessRole.EXPORT_SERVICE in policy.mask_by_default_roles

    def test_redaction_targets_cover_key_categories(self) -> None:
        policy = EvidencePrivacyPolicy()
        assert EvidenceRedactionTarget.FACE in policy.redaction_targets
        assert EvidenceRedactionTarget.LICENSE_PLATE in policy.redaction_targets
        assert EvidenceRedactionTarget.PERSONALLY_IDENTIFYING_DETAIL in policy.redaction_targets

    def test_enforcement_notes_are_honest(self) -> None:
        policy = EvidencePrivacyPolicy()
        notes_text = " ".join(policy.enforcement_notes)
        assert "not yet" in notes_text.lower() or "policy foundation" in notes_text.lower()

    def test_compliance_notes_are_honest(self) -> None:
        policy = EvidencePrivacyPolicy()
        notes_text = " ".join(policy.compliance_notes)
        assert "does not claim" in notes_text.lower() or "foundation" in notes_text.lower()


# ===========================================================================
# EvidenceManifestDocument legacy normalization
# ===========================================================================


class TestLegacyManifestNormalization:
    def test_old_manifest_without_privacy_fields_gets_defaults(self) -> None:
        raw = {
            "subject": _make_subject().model_dump(mode="json"),
            "storage_namespace": "evidence",
            "selection_policy": {"event_frame_index": 42, "selection_reason": "test"},
            "timeline": {
                "occurred_at": _NOW.isoformat(),
                "event_frame_index": 42,
                "clip_window": {},
            },
            "assets": [_make_original_asset().model_dump(mode="json")],
        }
        doc = EvidenceManifestDocument.model_validate(raw)
        assert doc.privacy_policy.policy_name == "default_evidence_redaction_v1"
        assert doc.active_asset_view == EvidenceAssetView.ORIGINAL
        assert doc.original_asset_count == 1
        assert doc.redacted_asset_count == 0


# ===========================================================================
# Redacted asset provenance
# ===========================================================================


class TestRedactedAssetProvenance:
    def test_redacted_asset_references_original(self) -> None:
        orig = _make_original_asset()
        redacted = _make_redacted_asset()
        assert redacted.derived_from_asset_key == orig.asset_key

    def test_redacted_asset_has_planned_status(self) -> None:
        redacted = _make_redacted_asset()
        assert redacted.redaction_status == EvidenceRedactionStatus.PLANNED
        assert redacted.storage_state == EvidenceStorageState.PLANNED

    def test_redacted_asset_has_redacted_view(self) -> None:
        redacted = _make_redacted_asset()
        assert redacted.asset_view == EvidenceAssetView.REDACTED

    def test_redacted_asset_preserves_targets(self) -> None:
        redacted = _make_redacted_asset()
        assert EvidenceRedactionTarget.FACE in redacted.redaction_targets
        assert EvidenceRedactionTarget.LICENSE_PLATE in redacted.redaction_targets


# ===========================================================================
# Integration: full access flow
# ===========================================================================


class TestFullAccessFlow:
    def test_operator_full_flow(self) -> None:
        """Operator sees redacted assets, plate text masked, restricted originals flagged."""
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.OPERATOR,
            requested_view=None,
        )
        document = _make_document()

        assert access.resolved_view == EvidenceAssetView.REDACTED
        visible = resolve_visible_assets(document=document, access=access)
        assert all(a.asset_view == EvidenceAssetView.REDACTED for a in visible)

        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.active_asset_view == EvidenceAssetView.REDACTED
        assert sanitized.audit.get("restricted_original_assets") is True

    def test_privacy_officer_full_flow(self) -> None:
        """Privacy officer sees original assets when requested."""
        policy = EvidencePrivacyPolicy()
        access = resolve_access_resolution(
            policy=policy,
            role=EvidenceAccessRole.PRIVACY_OFFICER,
            requested_view=EvidenceAssetView.ORIGINAL,
        )
        document = _make_document()

        assert access.resolved_view == EvidenceAssetView.ORIGINAL
        visible = resolve_visible_assets(document=document, access=access)
        assert all(a.asset_view == EvidenceAssetView.ORIGINAL for a in visible)

        sanitized = sanitize_manifest_for_access(document=document, access=access)
        assert sanitized.active_asset_view == EvidenceAssetView.ORIGINAL
        assert sanitized.audit.get("restricted_original_assets") is not True

    def test_plate_text_masked_in_redacted_flow(self) -> None:
        """Plate text is masked when access is redacted."""
        original = "ABC1234"
        masked = mask_plate_text(original)
        assert masked != original
        assert masked is not None
        assert len(masked) == len(original)
