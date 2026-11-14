from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    Post,
)
from tkb_engine import Conclusion, Gazetteer
from tkb_engine.cross_post import infer_owner_claims

SCRIPT = Path(__file__).resolve().parents[2] / "eval" / "mock_inference_report.py"
SPEC = importlib.util.spec_from_file_location("mock_inference_report", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def _clue(post_id: str, value: str, type_: ClueType = ClueType.ROUTINE_TEXT) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=None,
        type=type_,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def test_evidence_indices_resolve_to_the_correct_clue_without_exposing_source_text() -> None:
    clues = [_clue("post-a", "private source text"), _clue("post-b", "other source")]
    serialized = module._serialize([Conclusion("R3", "routine", "claim", [1])], clues)
    assert serialized[0]["evidence"] == [
        {
            "clue_index": 1,
            "post_id": "post-b",
            "type": "routine_text",
            "image_index": None,
            "region": None,
            "source": "text",
        }
    ]
    assert "value" not in serialized[0]["evidence"][0]


def test_partial_truth_does_not_call_other_predictions_false_positives() -> None:
    post = Post(
        post_id="post-a",
        text="",
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )
    predictions = infer_owner_claims([post], [])
    report = module._truth_report(
        predictions,
        {
            "complete": False,
            "status": "provisional",
            "claims": [{"attribute": "school", "value": "Tokyo"}],
        },
    )
    assert report["false_positives"] is None
    assert report["missed_expected_claims"] is None
    assert report["provisional_candidates_not_in_inference"] == [
        {"attribute": "school", "value": "Tokyo"}
    ]


def test_complete_confirmed_truth_can_report_a_missed_claim() -> None:
    report = module._truth_report(
        [],
        {
            "complete": True,
            "status": "confirmed",
            "claims": [{"attribute": "school", "value": "Tokyo"}],
        },
    )
    assert report["false_positives"] == []
    assert report["missed_expected_claims"] == [{"attribute": "school", "value": "Tokyo"}]


def test_profile_inference_is_recomputed_after_excluding_a_required_post() -> None:
    anchor = Post(
        post_id="post-a",
        text="自宅近くの青葉商店街",
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )
    supporting = Post(
        post_id="post-b",
        text="青葉商店街は文京区",
        created_at=datetime.fromisoformat("2026-10-21T08:31:00+09:00"),
        images=[],
    )
    clue = _clue("post-b", "文京区", ClueType.PLACE_TEXT)
    document = {
        "posts": [anchor.model_dump(mode="json"), supporting.model_dump(mode="json")],
        "clues": [clue.model_dump(mode="json")],
        "annotation_kind": "manual",
    }
    report = module.build_report(document, [anchor.post_id], Gazetteer())
    before = report["claims"]["profile_inference"]["before"]
    after = report["claims"]["profile_inference"]["after"]
    residence = next(item for item in before if item["attribute"] == "residential_area")
    path_evidence = residence["evidence_paths"][0]["evidence"]
    assert any(
        item.get("clue_index") == 0 and item["post_id"] == supporting.post_id
        for item in path_evidence
    )
    assert after == []
    assert report["notes"][-2] == "Clues are manually annotated and are not OCR/VLM results."


def test_candidate_set_evaluation_is_separate_and_labeled_by_annotation_track() -> None:
    candidate_sets = [
        {
            "attribute": attribute,
            "status": "unknown",
            "candidates": [],
            "reason": "no grounded candidate",
        }
        for attribute in sorted(module.PROFILE_CANDIDATE_ATTRIBUTES)
    ]
    report = module.build_report(
        {"posts": [], "clues": [], "annotation_kind": "manual"},
        [],
        Gazetteer(),
        {"status": "confirmed", "complete": True, "claims": []},
        {"stations": True, "postal": True, "muni_mesh": True, "schools": True},
        candidate_sets,
    )
    assert report["evaluation_track"] == "manual_annotation_rule_evaluation"
    candidate_eval = report["candidate_set_truth_evaluation"]
    assert candidate_eval["accuracy_metrics"]["wrong_candidate_rate"] == 0.0
    assert candidate_eval["candidate_status_rates"]["unknown_count"] == 24


def test_candidate_report_rejects_incomplete_attribute_sets() -> None:
    all_sets = [
        {
            "attribute": attribute,
            "status": "unknown",
            "candidates": [],
            "reason": "no grounded candidate",
        }
        for attribute in sorted(module.PROFILE_CANDIDATE_ATTRIBUTES)
    ]
    for incomplete in ([], all_sets[:-1]):
        try:
            module.build_report(
                {"posts": [], "clues": []},
                [],
                Gazetteer(),
                {"status": "confirmed", "complete": True, "claims": []},
                candidate_sets=incomplete,
            )
        except ValueError as error:
            assert "exactly 24 unique attributes" in str(error)
        else:
            raise AssertionError("an empty or incomplete candidate set array must be rejected")


def test_report_output_must_stay_in_ignored_eval_local() -> None:
    assert module._output_path(module.ROOT / "local" / "report.json").name == "report.json"
    try:
        module._output_path(module.ROOT / "fixtures" / "report.json")
    except ValueError:
        pass
    else:
        raise AssertionError("output outside eval/local should be rejected")
