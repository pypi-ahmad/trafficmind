"""Deterministic helpers for grounded multimodal review assistance.

This module keeps the multimodal review workflow boundary explicit: the
workflow can summarize stored metadata, evidence manifests, and attached
media references, but it never replaces deterministic violation logic or
rewrites source records.
"""

from __future__ import annotations

from apps.workflow.app.workflows.schemas import MultimodalReviewContext, MultimodalReviewGrounding, PriorReviewRecord


MULTIMODAL_REVIEW_BOUNDARY_NOTE = (
    "This workflow is advisory only; deterministic violation logic and stored source records remain the system of record."
)

_ATTACHED_MEDIA_SOURCES = frozenset({"detection_event", "violation_event", "plate_read"})


def _available_labels(context: MultimodalReviewContext, *, source_group: str, kind: str) -> list[str]:
    references = context.image_references if kind == "image" else context.clip_references
    labels: list[str] = []
    for item in references:
        if not item.available:
            continue
        is_attached = item.source in _ATTACHED_MEDIA_SOURCES
        if source_group == "attached" and not is_attached:
            continue
        if source_group == "manifest" and is_attached:
            continue
        labels.append(item.label)
    return labels


def _media_basis_phrase(grounding: MultimodalReviewGrounding) -> str:
    attached_images = bool(grounding.attached_image_labels)
    attached_clips = bool(grounding.attached_clip_labels)
    manifest_images = bool(grounding.manifest_image_labels)
    manifest_clips = bool(grounding.manifest_clip_labels)

    if attached_images and attached_clips:
        return "directly attached images and clips"
    if attached_images:
        return "directly attached still images plus stored metadata"
    if attached_clips:
        return "a directly attached clip plus stored metadata"
    if manifest_images or manifest_clips:
        return "manifest-linked media references plus stored metadata"
    return "stored metadata and manifest references only"


def build_multimodal_review_grounding(
    context: MultimodalReviewContext,
) -> MultimodalReviewGrounding:
    image_refs = context.image_references
    clip_refs = context.clip_references
    attached_image_labels = _available_labels(context, source_group="attached", kind="image")
    attached_clip_labels = _available_labels(context, source_group="attached", kind="clip")
    manifest_image_labels = _available_labels(context, source_group="manifest", kind="image")
    manifest_clip_labels = _available_labels(context, source_group="manifest", kind="clip")
    planned_media = [
        item.label
        for item in [*image_refs, *clip_refs]
        if not item.available
    ]
    notes: list[str] = []
    if not attached_image_labels and not attached_clip_labels and not manifest_image_labels and not manifest_clip_labels:
        notes.append(
            "No attached images or clips are available; the review is grounded in metadata, evidence manifests, and prior notes only."
        )
    elif not attached_image_labels and not attached_clip_labels and (manifest_image_labels or manifest_clip_labels):
        notes.append(
            "No direct attached images or clips are persisted on the source records; the review depends on manifest-linked media references and stored metadata."
        )
    elif not attached_clip_labels and not manifest_clip_labels:
        notes.append(
            "No attached clip is available, so temporal confirmation depends on still images and stored rule metadata."
        )
    if planned_media:
        notes.append(
            "Some referenced media assets are still planned or unavailable: "
            + ", ".join(planned_media[:3])
            + "."
        )
    if not context.rule_explanation.reason:
        notes.append(
            "Rule explanation details are sparse, so the review falls back to the stored violation summary and metadata."
        )
    if _has_prior_review_disagreement(context.prior_review_history):
        notes.append(
            "Prior review history is not fully aligned, so a final operator decision should confirm which disposition is authoritative."
        )

    return MultimodalReviewGrounding(
        metadata_reference_count=len(context.metadata_references),
        image_reference_count=len(context.image_references),
        clip_reference_count=len(context.clip_references),
        manifest_reference_count=len(context.manifest_references),
        attached_image_labels=attached_image_labels,
        attached_clip_labels=attached_clip_labels,
        manifest_image_labels=manifest_image_labels,
        manifest_clip_labels=manifest_clip_labels,
        available_image_labels=[item.label for item in image_refs if item.available],
        available_clip_labels=[item.label for item in clip_refs if item.available],
        planned_media_labels=planned_media,
        prior_review_count=len(context.prior_review_history),
        grounding_notes=notes,
    )


def build_multimodal_review_summary(
    context: MultimodalReviewContext,
    grounding: MultimodalReviewGrounding,
) -> str:
    violation_label = context.violation_event.violation_type.value.replace("_", " ")
    evidence_phrase = _media_basis_phrase(grounding)

    return (
        f"Stored {violation_label} violation at {context.camera.location_name} is ready for operator review using"
        f" {evidence_phrase}; this copilot summary is advisory."
    )


def build_multimodal_review_likely_cause(context: MultimodalReviewContext) -> str:
    reason = context.rule_explanation.reason or context.violation_event.summary
    if reason:
        text = reason.rstrip(".") + "."
    else:
        violation_label = context.violation_event.violation_type.value.replace("_", " ")
        signal_state = _signal_state(context)
        if signal_state is not None:
            text = f"Stored {violation_label} rule metadata indicates the relevant signal state was {signal_state}."
        else:
            text = f"Stored {violation_label} rule metadata triggered the persisted violation event."

    anchors: list[str] = []
    if context.rule_explanation.rule_type:
        anchors.append(f"rule_type={context.rule_explanation.rule_type}")
    signal_state = _signal_state(context)
    if signal_state is not None:
        anchors.append(f"signal_state={signal_state}")
    track_id = context.rule_explanation.salient_details.get("track_id")
    if isinstance(track_id, str) and track_id:
        anchors.append(f"track_id={track_id}")
    if context.rule_explanation.frame_index is not None:
        anchors.append(f"frame_index={context.rule_explanation.frame_index}")
    if context.detection_event is not None:
        anchors.append(f"detection_confidence={context.detection_event.confidence:.2f}")

    if anchors:
        return f"{text} Grounded anchors: {', '.join(anchors)}."
    return text


def build_multimodal_review_caveats(
    context: MultimodalReviewContext,
    grounding: MultimodalReviewGrounding,
) -> list[str]:
    caveats = list(grounding.grounding_notes)
    detection = context.detection_event
    if detection is not None and detection.confidence < 0.7:
        caveats.append(
            f"Linked detection confidence is only {detection.confidence:.2f}, so the operator should verify the track in context."
        )
    if any(not item.available for item in context.manifest_references):
        caveats.append(
            "One or more evidence manifests are referenced but not directly fetchable from the stored URI, so operators may need to reopen the record through the API."
        )
    return caveats


def build_multimodal_review_action(
    context: MultimodalReviewContext,
    grounding: MultimodalReviewGrounding,
) -> str:
    if not grounding.attached_image_labels and not grounding.attached_clip_labels and not grounding.manifest_image_labels and not grounding.manifest_clip_labels:
        return (
            "Open the stored evidence manifest, verify the selected event frame and rule metadata, and request rendered media before making a final decision."
        )
    if not grounding.attached_image_labels and not grounding.attached_clip_labels and (grounding.manifest_image_labels or grounding.manifest_clip_labels):
        return (
            "Open the manifest-linked media references, verify them against the stored rule explanation, and request direct attachments if the operator tooling cannot render them cleanly."
        )
    if (grounding.attached_image_labels or grounding.manifest_image_labels) and not (grounding.attached_clip_labels or grounding.manifest_clip_labels):
        return (
            "Inspect the available still-image evidence against the stored rule explanation and request a clip window if temporal confirmation is still needed."
        )
    return (
        f"Review the available media ({_media_basis_phrase(grounding)}) alongside the stored rule explanation before confirming or dismissing the case."
    )


def build_multimodal_review_escalation(
    context: MultimodalReviewContext,
    grounding: MultimodalReviewGrounding,
) -> str | None:
    if _signal_conflict_reason(context) is not None:
        return "Escalate to a supervisor or signal-integration operator because stored signal-source metadata reports a conflict."
    if _has_prior_review_disagreement(context.prior_review_history):
        return "Escalate for supervisor adjudication because prior review history shows conflicting dispositions."
    if (
        not grounding.attached_image_labels
        and not grounding.attached_clip_labels
        and not grounding.manifest_image_labels
        and not grounding.manifest_clip_labels
        and context.violation_event.severity.value in {"high", "critical"}
    ):
        return "Escalate if a disposition is needed before rendered media can be retrieved for this high-severity case."
    return None


def build_multimodal_review_audit_notes(
    context: MultimodalReviewContext,
    grounding: MultimodalReviewGrounding,
) -> list[str]:
    return [
        (
            f"Grounded in {grounding.metadata_reference_count} metadata reference(s),"
            f" {grounding.image_reference_count} image reference(s),"
            f" {grounding.clip_reference_count} clip reference(s), and"
            f" {grounding.manifest_reference_count} manifest reference(s)."
        ),
        (
            "Direct attached media available: "
            + (
                ", ".join([*grounding.attached_image_labels, *grounding.attached_clip_labels])
                if grounding.attached_image_labels or grounding.attached_clip_labels
                else "none"
            )
            + "."
        ),
        (
            "Manifest-linked media available: "
            + (
                ", ".join([*grounding.manifest_image_labels, *grounding.manifest_clip_labels])
                if grounding.manifest_image_labels or grounding.manifest_clip_labels
                else "none"
            )
            + "."
        ),
        f"Prior review history entries considered: {grounding.prior_review_count}.",
        MULTIMODAL_REVIEW_BOUNDARY_NOTE,
        *(
            [f"Caller operator note: {context.review_context.operator_notes}"]
            if context.review_context.operator_notes
            else []
        ),
    ]


def _has_prior_review_disagreement(history: list[PriorReviewRecord]) -> bool:
    dispositions = {item.disposition for item in history if item.disposition}
    return len(dispositions) > 1


def _signal_state(context: MultimodalReviewContext) -> str | None:
    for key in ("signal_state_at_decision", "signal_state_at_detection", "light_state"):
        value = context.rule_explanation.salient_details.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _signal_conflict_reason(context: MultimodalReviewContext) -> str | None:
    value = context.rule_explanation.salient_details.get("signal_conflict_reason")
    if isinstance(value, str) and value:
        return value
    return None