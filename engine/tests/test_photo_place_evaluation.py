from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from photo_place_evaluation import DEFAULT_FIXTURE, _load_document, evaluate_document  # noqa: E402


def test_synthetic_photo_place_harness_measures_abstention_and_deletion() -> None:
    report = evaluate_document(_load_document(DEFAULT_FIXTURE))

    assert report["evaluation_kind"] == "synthetic_no_images"
    assert report["metrics"] == {
        "identifiable_case_count": 8,
        "candidate_coverage": 1.0,
        "correct_candidate_rate": 1.0,
        "unknown_precision": 1.0,
        "unknown_prediction_count": 1,
        "ambiguous_single_assertion_rate": 0.0,
        "forbidden_location_claim_count": 0,
        "forbidden_location_claim_case_rate": 0.0,
        "deletion_path_drop_rate": 1.0,
        "deletion_path_drop_checks": 2,
    }
    assert report["cases"][0]["deletion_paths_dropped"] == 2


def test_candidate_recall_uses_independent_expected_place_ids() -> None:
    document = _load_document(DEFAULT_FIXTURE)
    document["cases"][0]["expected_place_ids"] = ["fixture:not-the-returned-place"]

    report = evaluate_document(document)

    assert report["metrics"]["candidate_coverage"] == 1.0
    assert report["metrics"]["correct_candidate_rate"] == 0.875
    assert report["cases"][0]["predicted_place_ids"] == ["fixture:green-hall"]


def test_fixture_loader_rejects_image_based_evaluations(tmp_path: Path) -> None:
    fixture: dict[str, Any] = {"evaluation_kind": "public_images", "places": [], "cases": []}
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    try:
        _load_document(path)
    except ValueError as exc:
        assert "synthetic_no_images" in str(exc)
    else:
        raise AssertionError("image-based evaluation fixture should be rejected")
