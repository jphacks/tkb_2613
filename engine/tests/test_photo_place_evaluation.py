from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = ROOT / "eval" / "fixtures" / "photo_place_synthetic.json"
EVALUATOR = ROOT / "eval" / "photo_place_evaluation.py"


def _run_evaluator(fixture: Path = DEFAULT_FIXTURE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed local interpreter/script; fixture is a local file
        [sys.executable, str(EVALUATOR), str(fixture)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def test_synthetic_photo_place_harness_measures_abstention_and_deletion() -> None:
    process = _run_evaluator()
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)

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


def test_candidate_recall_uses_independent_expected_place_ids(tmp_path: Path) -> None:
    document = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    document["cases"][0]["expected_place_ids"] = ["fixture:not-the-returned-place"]
    fixture = tmp_path / "metric-check.json"
    fixture.write_text(json.dumps(document), encoding="utf-8")
    process = _run_evaluator(fixture)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)

    assert report["metrics"]["candidate_coverage"] == 1.0
    assert report["metrics"]["correct_candidate_rate"] == 0.875
    assert report["cases"][0]["predicted_place_ids"] == ["fixture:green-hall"]


def test_fixture_loader_rejects_image_based_evaluations(tmp_path: Path) -> None:
    fixture: dict[str, Any] = {
        "evaluation_kind": "public_images",
        "annotation_kind": "manual",
        "places": [],
        "cases": [],
    }
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    process = _run_evaluator(path)
    assert process.returncode != 0
    assert "synthetic_no_images" in process.stderr
