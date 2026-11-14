"""Score bounded profile candidate sets against complete, confirmed annotations.

Evidence scores describe agreement with the annotation and reference integrity only;
they do not establish that an inference is causally justified.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from tkb_common.schemas import ProfileAttribute

PROFILE_CANDIDATE_ATTRIBUTES = {
    attribute.value for attribute in ProfileAttribute if attribute is not ProfileAttribute.HOME_ROOM
}
if len(PROFILE_CANDIDATE_ATTRIBUTES) != 29:
    raise RuntimeError(
        "ProfileAttribute schema must expose 29 diagnosed attributes excluding home_room"
    )


def _pair(attribute: str, value: str) -> dict[str, str]:
    return {"attribute": attribute, "value": value}


def _canonical_value(value: str) -> str:
    """Normalize displayed and annotated strings consistently for value matching."""
    return unicodedata.normalize("NFKC", value).strip().lower()


def _ref_key(
    ref: Mapping[str, Any],
) -> tuple[str | None, int | None, int | None, str | None]:
    post_id = ref.get("post_id")
    clue_index = ref.get("clue_index")
    image_index = ref.get("image_index")
    web_fact_id = ref.get("web_fact_id")
    if post_id is not None and not isinstance(post_id, str):
        raise ValueError("evidence post_id must be a string or null")
    if clue_index is not None and type(clue_index) is not int:
        raise ValueError("evidence clue_index must be an integer or null")
    if image_index is not None and type(image_index) is not int:
        raise ValueError("evidence image_index must be an integer or null")
    if web_fact_id is not None and not isinstance(web_fact_id, str):
        raise ValueError("evidence web_fact_id must be a string or null")
    return (
        post_id,
        clue_index,
        image_index,
        web_fact_id,
    )


def _candidate_refs(
    candidate: Mapping[str, Any],
    provenance_scope: str = "all",
) -> tuple[
    list[set[tuple[str | None, int | None, int | None, str | None]]],
    set[tuple[str | None, int | None, int | None, str | None]],
]:
    paths: list[set[tuple[str | None, int | None, int | None, str | None]]] = []
    all_refs: set[tuple[str | None, int | None, int | None, str | None]] = set()
    raw_paths = candidate.get("evidence_paths", [])
    if not isinstance(raw_paths, list):
        return paths, all_refs
    for path in raw_paths:
        if not isinstance(path, Mapping) or not isinstance(path.get("evidence", []), list):
            continue
        if provenance_scope != "all" and path.get("provenance", "unclassified") != provenance_scope:
            continue
        refs = {_ref_key(ref) for ref in path.get("evidence", []) if isinstance(ref, Mapping)}
        paths.append(refs)
        all_refs.update(refs)
    return paths, all_refs


def _has_provenance(candidate: Mapping[str, Any], provenance: str) -> bool:
    raw_paths = candidate.get("evidence_paths", [])
    return isinstance(raw_paths, list) and any(
        isinstance(path, Mapping) and path.get("provenance", "unclassified") == provenance
        for path in raw_paths
    )


def _scoped_candidates(row: Mapping[str, Any] | None, provenance_scope: str) -> list[Any]:
    candidates = row.get("candidates", []) if row else []
    if not isinstance(candidates, list):
        raise ValueError("candidate set candidates must be an array")
    if provenance_scope == "all":
        return candidates
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, Mapping) and _has_provenance(candidate, provenance_scope)
    ]


def _validate_candidate_set_attributes(
    candidate_sets: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(candidate_sets, Sequence) or isinstance(candidate_sets, (str, bytes)):
        raise ValueError("candidate sets must be an array")
    rows_by_attribute: dict[str, Mapping[str, Any]] = {}
    for row in candidate_sets:
        if not isinstance(row, Mapping) or not isinstance(row.get("attribute"), str):
            raise ValueError("candidate sets require an attribute")
        attribute = row["attribute"]
        if attribute in rows_by_attribute:
            raise ValueError("candidate sets must have unique attributes")
        rows_by_attribute[attribute] = row
    if set(rows_by_attribute) != PROFILE_CANDIDATE_ATTRIBUTES:
        missing = PROFILE_CANDIDATE_ATTRIBUTES - set(rows_by_attribute)
        extra = set(rows_by_attribute) - PROFILE_CANDIDATE_ATTRIBUTES
        raise ValueError(
            "candidate sets must contain exactly the 29 supported attributes "
            f"(missing: {sorted(missing)}, extra: {sorted(extra)})"
        )
    return rows_by_attribute


def evaluate_candidate_sets(
    candidate_sets: Sequence[Mapping[str, Any]],
    truth: Any,
    *,
    post_ids: set[str] | None = None,
    post_images: Mapping[str, set[int]] | None = None,
    clues: Sequence[Mapping[str, Any]] | None = None,
    web_fact_ids: set[str] | None = None,
    provenance_scope: str = "all",
) -> dict[str, Any]:
    """Return candidate-set metrics, withholding accuracy unless truth is complete+confirmed."""
    if provenance_scope not in {
        "all",
        "direct_disclosure",
        "combined_inference",
        "unclassified",
    }:
        raise ValueError("invalid evidence path provenance scope")
    rows_by_attribute = _validate_candidate_set_attributes(candidate_sets)
    if not isinstance(truth, Mapping) or not isinstance(truth.get("claims"), list):
        truth = {}
    claims = truth.get("claims", [])
    if any(
        not isinstance(claim, Mapping)
        or not isinstance(claim.get("attribute"), str)
        or not claim["attribute"].strip()
        or not isinstance(claim.get("value"), str)
        or not claim["value"].strip()
        for claim in claims
    ):
        raise ValueError("truth claims require string attribute and value fields")
    status = truth.get("status", "unspecified")
    if status not in {"unspecified", "provisional", "confirmed"}:
        raise ValueError("truth status must be unspecified, provisional, or confirmed")
    complete = truth.get("complete") is True
    eligible = status == "confirmed" and complete

    expected: dict[str, set[str]] = defaultdict(set)
    for claim in claims:
        if claim["attribute"] not in PROFILE_CANDIDATE_ATTRIBUTES:
            raise ValueError("truth contains an attribute outside the 29 diagnosed attributes")
        expected[claim["attribute"]].add(_canonical_value(claim["value"]))

    top1_correct = top1_total = covered = truth_value_count = 0
    wrong_candidates: list[dict[str, str]] = []
    displayed_count = 0
    unknown_count = conflict_count = 0
    scoped_status_counts = {"candidate": 0, "ambiguous": 0, "unknown": 0}
    reference_checked = reference_valid = reference_invalid = 0
    evidence_annotated = evidence_exact_path_matches = 0
    reference_tp = reference_fp = reference_fn = 0
    invalid_refs: list[dict[str, Any]] = []
    scoped_candidates_by_attribute: dict[str, list[Any]] = {}

    for row in candidate_sets:
        attribute = row["attribute"]
        row_status = row.get("status")
        candidates = _scoped_candidates(row, provenance_scope)
        scoped_candidates_by_attribute[attribute] = candidates
        unknown_count += row_status == "unknown"
        conflict_count += row_status == "conflict"
        scoped_status = (
            "unknown" if not candidates else "candidate" if len(candidates) == 1 else "ambiguous"
        )
        scoped_status_counts[scoped_status] += 1
        truth_values = expected.get(attribute, set())

        for candidate in candidates:
            if not isinstance(candidate, Mapping) or not isinstance(candidate.get("value"), str):
                raise ValueError("candidates require string values")
            if not candidate["value"].strip():
                raise ValueError("candidate values must not be blank")
            displayed_count += 1
            if eligible and _canonical_value(candidate["value"]) not in truth_values:
                wrong_candidates.append(_pair(attribute, candidate["value"]))
            paths, _refs = _candidate_refs(candidate, provenance_scope)
            for path_index, path in enumerate(paths):
                for ref in path:
                    post_id, clue_index, image_index, web_fact_id = ref
                    checked = any(
                        value is not None
                        for value in (post_id, clue_index, image_index, web_fact_id)
                    )
                    if not checked:
                        continue
                    reference_checked += 1
                    valid = post_id is None or post_ids is None or post_id in post_ids
                    if clue_index is not None:
                        valid = valid and clues is not None and 0 <= clue_index < len(clues)
                        if valid and post_id is not None:
                            valid = clues[clue_index].get("post_id") == post_id
                        if valid and image_index is not None:
                            valid = clues[clue_index].get("image_index") == image_index
                    if image_index is not None:
                        valid = valid and post_id is not None
                        if valid and post_images is not None:
                            valid = image_index in post_images.get(post_id, set())
                    if web_fact_id is not None and web_fact_ids is not None:
                        valid = valid and web_fact_id in web_fact_ids
                    if valid:
                        reference_valid += 1
                    else:
                        reference_invalid += 1
                        invalid_refs.append(
                            {
                                "attribute": attribute,
                                "candidate": candidate["value"],
                                "path_index": path_index,
                                "post_id": post_id,
                                "clue_index": clue_index,
                                "image_index": image_index,
                                "web_fact_id": web_fact_id,
                            }
                        )

    for truth_claim in (claim for claim in claims if claim.get("evidence_paths")):
        evidence_annotated += 1
        expected_paths = truth_claim["evidence_paths"]
        if not isinstance(expected_paths, list):
            raise ValueError("truth evidence_paths must be an array")
        expected_path_sets: list[set[tuple[str | None, int | None, int | None, str | None]]] = []
        for expected_path in expected_paths:
            if not isinstance(expected_path, list) or not all(
                isinstance(ref, Mapping) for ref in expected_path
            ):
                raise ValueError("each truth evidence path must be an array of reference objects")
            expected_path_sets.append({_ref_key(ref) for ref in expected_path})
        expected_refs = set().union(*expected_path_sets) if expected_path_sets else set()
        row = rows_by_attribute.get(truth_claim["attribute"])
        row_candidates = scoped_candidates_by_attribute.get(truth_claim["attribute"], [])
        matching = next(
            (
                candidate
                for candidate in row_candidates
                if isinstance(candidate, Mapping)
                and isinstance(candidate.get("value"), str)
                and _canonical_value(candidate["value"]) == _canonical_value(truth_claim["value"])
            ),
            None,
        )
        predicted_paths, predicted_refs = (
            _candidate_refs(matching, provenance_scope) if matching else ([], set())
        )
        if any(path in expected_path_sets for path in predicted_paths):
            evidence_exact_path_matches += 1
        reference_tp += len(predicted_refs & expected_refs)
        reference_fp += len(predicted_refs - expected_refs)
        reference_fn += len(expected_refs - predicted_refs)

    truth_value_count = sum(len(values) for values in expected.values())
    top1_total = len(expected)
    for attribute, truth_values in expected.items():
        candidates = scoped_candidates_by_attribute.get(attribute, [])
        if (
            candidates
            and isinstance(candidates[0], Mapping)
            and isinstance(candidates[0].get("value"), str)
            and _canonical_value(candidates[0]["value"]) in truth_values
        ):
            top1_correct += 1
        displayed_values = {
            _canonical_value(c["value"])
            for c in candidates
            if isinstance(c, Mapping) and isinstance(c.get("value"), str)
        }
        covered += sum(value in displayed_values for value in truth_values)

    return {
        "assessed": eligible,
        "status": status,
        "complete": complete,
        "provenance_scope": provenance_scope,
        "scoring_scope": "displayed_candidates_only",
        "value_match_policy": "NFKC+trim+lower exact string match; no semantic matching",
        "accuracy_metrics": {
            "top1_accuracy": (
                top1_correct / top1_total
                if eligible and top1_total
                else (0.0 if eligible else None)
            ),
            "top1_correct": top1_correct if eligible else None,
            "top1_total": top1_total if eligible else None,
            "displayed_candidate_coverage": (
                covered / truth_value_count
                if eligible and truth_value_count
                else (0.0 if eligible else None)
            ),
            "covered_truth_values": covered if eligible else None,
            "truth_value_count": truth_value_count if eligible else None,
            "wrong_candidate_rate": (
                len(wrong_candidates) / displayed_count
                if eligible and displayed_count
                else (0.0 if eligible else None)
            ),
            "wrong_candidates": wrong_candidates if eligible else None,
            "displayed_candidate_count": displayed_count if eligible else None,
        },
        "candidate_status_rates": {
            "scope": "unfiltered_profile_claim_status",
            "unknown_rate": unknown_count / len(candidate_sets) if candidate_sets else 0.0,
            "unknown_count": unknown_count,
            "conflict_rate": conflict_count / len(candidate_sets) if candidate_sets else 0.0,
            "conflict_count": conflict_count,
            "set_count": len(candidate_sets),
        },
        "provenance_scoped_status_rates": {
            "scope": "status derived from candidates with selected provenance",
            "candidate_rate": (
                scoped_status_counts["candidate"] / len(candidate_sets) if candidate_sets else 0.0
            ),
            "candidate_count": scoped_status_counts["candidate"],
            "ambiguous_rate": (
                scoped_status_counts["ambiguous"] / len(candidate_sets) if candidate_sets else 0.0
            ),
            "ambiguous_count": scoped_status_counts["ambiguous"],
            "unknown_rate": (
                scoped_status_counts["unknown"] / len(candidate_sets) if candidate_sets else 0.0
            ),
            "unknown_count": scoped_status_counts["unknown"],
            "set_count": len(candidate_sets),
        },
        "evidence_reference_integrity": {
            "checked": reference_checked,
            "valid": reference_valid,
            "invalid": reference_invalid,
            "valid_rate": reference_valid / reference_checked if reference_checked else None,
            "invalid_references": invalid_refs,
        },
        "evidence_annotation_agreement": {
            "meaning": "annotation alignment only; not causal truth",
            "annotated_claims": evidence_annotated,
            "exact_path_matches": evidence_exact_path_matches,
            "exact_path_match_rate": (
                evidence_exact_path_matches / evidence_annotated if evidence_annotated else None
            ),
            "reference_precision": (
                reference_tp / (reference_tp + reference_fp)
                if reference_tp + reference_fp
                else None
            ),
            "reference_recall": (
                reference_tp / (reference_tp + reference_fn)
                if reference_tp + reference_fn
                else None
            ),
            "reference_true_positive": reference_tp,
            "reference_false_positive": reference_fp,
            "reference_false_negative": reference_fn,
        },
    }
