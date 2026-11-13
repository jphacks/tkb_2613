from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "eval" / "candidate_evaluation.py"
SPEC = importlib.util.spec_from_file_location("candidate_evaluation", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
_ALL_ATTRIBUTES = module.PROFILE_CANDIDATE_ATTRIBUTES


def _candidate(value: str, path: list[dict[str, object]]) -> dict[str, object]:
    return {
        "value": value,
        "confidence": 0.7,
        "evidence_paths": [{"confidence": 0.7, "evidence": path}],
    }


def _complete_sets(*rows: dict[str, object]) -> list[dict[str, object]]:
    by_attribute = {row["attribute"]: row for row in rows}
    return [
        by_attribute.get(
            attribute,
            {
                "attribute": attribute,
                "status": "unknown",
                "candidates": [],
                "reason": "no evidence",
            },
        )
        for attribute in sorted(_ALL_ATTRIBUTES)
    ]


def test_candidate_evaluation_rejects_empty_or_incomplete_sets_before_scoring() -> None:
    valid_set = _complete_sets()
    for invalid_set in ([], valid_set[:-1], [*valid_set, valid_set[0]]):
        try:
            module.evaluate_candidate_sets(
                invalid_set,
                {"status": "confirmed", "complete": True, "claims": []},
            )
        except ValueError as error:
            assert "29" in str(error) or "unique" in str(error)
        else:
            raise AssertionError("an incomplete candidate set must be rejected")


def test_complete_truth_scores_top1_coverage_false_candidates_and_unknowns() -> None:
    rows = _complete_sets(
        {
            "attribute": "regular_station",
            "status": "ambiguous",
            "candidates": [
                _candidate("根津駅", [{"post_id": "p1", "clue_index": 0}]),
                _candidate("千駄木駅", [{"post_id": "p2", "clue_index": 1}]),
            ],
        },
    )
    result = module.evaluate_candidate_sets(
        rows,
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {"attribute": "regular_station", "value": "根津駅"},
            ],
        },
        post_ids={"p1", "p2"},
        clues=[{"post_id": "p1"}, {"post_id": "p2"}],
    )
    metrics = result["accuracy_metrics"]
    assert metrics["top1_accuracy"] == 1.0
    assert metrics["displayed_candidate_coverage"] == 1.0
    assert metrics["wrong_candidate_rate"] == 0.5
    assert metrics["wrong_candidates"] == [{"attribute": "regular_station", "value": "千駄木駅"}]
    assert result["candidate_status_rates"]["unknown_count"] == 28
    assert result["candidate_status_rates"]["set_count"] == 29
    assert result["evidence_reference_integrity"]["valid_rate"] == 1.0


def test_provenance_scope_filters_all_value_metrics() -> None:
    direct = _candidate("根津駅", [{"post_id": "p1", "clue_index": 0}])
    direct["evidence_paths"] = [
        {
            "confidence": 0.7,
            "provenance": "direct_disclosure",
            "evidence": [{"post_id": "p1", "clue_index": 0}],
        }
    ]
    inferred = _candidate("千駄木駅", [{"post_id": "p3", "clue_index": 2}])
    inferred["evidence_paths"] = [
        {
            "confidence": 0.7,
            "provenance": "combined_inference",
            "evidence": [{"post_id": "p3", "clue_index": 2}],
        }
    ]
    rows = _complete_sets(
        {
            "attribute": "regular_station",
            "status": "ambiguous",
            "candidates": [direct, inferred],
        }
    )
    direct_truth = {
        "status": "confirmed",
        "complete": True,
        "claims": [{"attribute": "regular_station", "value": "根津駅"}],
    }
    inference_truth = {
        "status": "confirmed",
        "complete": True,
        "claims": [{"attribute": "regular_station", "value": "千駄木駅"}],
    }

    direct_result = module.evaluate_candidate_sets(
        rows, direct_truth, provenance_scope="direct_disclosure"
    )
    combined_vs_direct = module.evaluate_candidate_sets(
        rows, direct_truth, provenance_scope="combined_inference"
    )
    combined_result = module.evaluate_candidate_sets(
        rows, inference_truth, provenance_scope="combined_inference"
    )
    direct_vs_combined = module.evaluate_candidate_sets(
        rows, inference_truth, provenance_scope="direct_disclosure"
    )

    assert direct_result["accuracy_metrics"]["displayed_candidate_count"] == 1
    assert direct_result["accuracy_metrics"]["top1_correct"] == 1
    assert combined_vs_direct["accuracy_metrics"]["top1_correct"] == 0
    assert combined_vs_direct["accuracy_metrics"]["covered_truth_values"] == 0
    assert combined_result["accuracy_metrics"]["top1_correct"] == 1
    assert direct_vs_combined["accuracy_metrics"]["top1_correct"] == 0
    assert direct_vs_combined["accuracy_metrics"]["covered_truth_values"] == 0


def test_provenance_scoped_status_rates_mark_filtered_candidate_unknown() -> None:
    combined = _candidate("千駄木駅", [{"post_id": "p3", "clue_index": 2}])
    combined["evidence_paths"] = [
        {
            "confidence": 0.7,
            "provenance": "combined_inference",
            "evidence": [{"post_id": "p3", "clue_index": 2}],
        }
    ]
    rows = _complete_sets(
        {
            "attribute": "regular_station",
            "status": "candidate",
            "candidates": [combined],
        }
    )

    result = module.evaluate_candidate_sets(rows, {}, provenance_scope="direct_disclosure")

    assert result["candidate_status_rates"]["scope"] == "unfiltered_profile_claim_status"
    assert result["candidate_status_rates"]["unknown_count"] == 28
    assert result["provenance_scoped_status_rates"]["unknown_count"] == 29
    assert result["provenance_scoped_status_rates"]["unknown_rate"] == 1.0
    assert result["provenance_scoped_status_rates"]["candidate_count"] == 0


def test_accuracy_is_withheld_for_incomplete_truth_but_status_rates_remain() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(
            {
                "attribute": "regular_station",
                "status": "candidate",
                "candidates": [_candidate("根津駅", [])],
            }
        ),
        {
            "status": "confirmed",
            "complete": False,
            "claims": [{"attribute": "regular_station", "value": "根津駅"}],
        },
    )
    assert result["assessed"] is False
    assert result["accuracy_metrics"]["top1_accuracy"] is None
    assert result["candidate_status_rates"]["set_count"] == 29


def test_unknown_set_for_truth_attribute_counts_as_top1_miss_and_uncovered() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(),
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {"attribute": "regular_station", "value": "根津駅"},
            ],
        },
    )
    assert result["accuracy_metrics"]["top1_accuracy"] == 0.0
    assert result["accuracy_metrics"]["displayed_candidate_coverage"] == 0.0


def test_candidate_value_match_uses_documented_nfkc_lower_and_trim_normalization() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(
            {
                "attribute": "other_social_account",
                "status": "candidate",
                "candidates": [_candidate("  ＡＢＣ@Example.com  ", [])],
            }
        ),
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {
                    "attribute": "other_social_account",
                    "value": "abc@example.COM",
                }
            ],
        },
    )
    assert result["accuracy_metrics"]["top1_accuracy"] == 1.0
    assert result["accuracy_metrics"]["displayed_candidate_coverage"] == 1.0


def test_nfkc_lower_trim_does_not_casefold_sharp_s() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(
            {
                "attribute": "nickname",
                "status": "candidate",
                "candidates": [_candidate("Straße", [])],
            }
        ),
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {
                    "attribute": "nickname",
                    "value": "STRASSE",
                }
            ],
        },
    )
    assert result["accuracy_metrics"]["top1_accuracy"] == 0.0
    assert result["accuracy_metrics"]["displayed_candidate_coverage"] == 0.0
    assert result["accuracy_metrics"]["wrong_candidate_rate"] == 1.0


def test_scoring_uses_displayed_candidates_not_internal_candidate_pool() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(
            {
                "attribute": "regular_station",
                "status": "candidate",
                "candidates": [_candidate("千駄木駅", [])],
                "candidate_pool": [_candidate("根津駅", [])],
            }
        ),
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {
                    "attribute": "regular_station",
                    "value": "根津駅",
                }
            ],
        },
    )
    assert result["accuracy_metrics"]["top1_accuracy"] == 0.0
    assert result["accuracy_metrics"]["displayed_candidate_coverage"] == 0.0
    assert result["accuracy_metrics"]["wrong_candidates"] == [
        {"attribute": "regular_station", "value": "千駄木駅"}
    ]


def test_evidence_annotation_reports_exact_path_and_partial_reference_agreement() -> None:
    rows = _complete_sets(
        {
            "attribute": "regular_station",
            "status": "candidate",
            "candidates": [
                _candidate(
                    "根津駅",
                    [
                        {"post_id": "p1", "clue_index": 0},
                        {"post_id": "p2", "clue_index": 1},
                    ],
                )
            ],
        }
    )
    truth = {
        "status": "confirmed",
        "complete": True,
        "claims": [
            {
                "attribute": "regular_station",
                "value": "根津駅",
                "evidence_paths": [[{"post_id": "p1", "clue_index": 0}]],
            }
        ],
    }
    result = module.evaluate_candidate_sets(rows, truth)
    agreement = result["evidence_annotation_agreement"]
    assert agreement["exact_path_match_rate"] == 0.0
    assert agreement["reference_precision"] == 0.5
    assert agreement["reference_recall"] == 1.0
    assert agreement["meaning"].endswith("not causal truth")


def test_reference_integrity_checks_clue_post_consistency() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(
            {
                "attribute": "regular_station",
                "status": "candidate",
                "candidates": [_candidate("根津駅", [{"post_id": "p1", "clue_index": 0}])],
            }
        ),
        {"status": "provisional", "complete": False, "claims": []},
        post_ids={"p1"},
        clues=[{"post_id": "different-post"}],
    )
    assert result["accuracy_metrics"]["top1_accuracy"] is None
    assert result["evidence_reference_integrity"]["invalid"] == 1


def test_annotated_evidence_for_missing_candidate_is_counted_as_uncovered() -> None:
    result = module.evaluate_candidate_sets(
        _complete_sets(),
        {
            "status": "confirmed",
            "complete": True,
            "claims": [
                {
                    "attribute": "regular_station",
                    "value": "根津駅",
                    "evidence_paths": [[{"post_id": "post-a", "clue_index": 0}]],
                }
            ],
        },
    )
    agreement = result["evidence_annotation_agreement"]
    assert agreement["annotated_claims"] == 1
    assert agreement["exact_path_match_rate"] == 0.0
    assert agreement["reference_recall"] == 0.0
