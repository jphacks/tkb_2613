"""Evaluate photo-place abstention and cross-post safety on synthetic fixtures only."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys  # noqa: E402
from tkb_common.schemas import (  # noqa: E402
    Clue,
    PhotoPlaceResult,
    Post,
    ProfileAttribute,
    ProfileCandidateSet,
)
from tkb_engine.cross_post import infer_owner_candidate_sets_with_web  # noqa: E402
from tkb_engine.gazetteer import Gazetteer  # noqa: E402
from tkb_engine.photo_place import infer_photo_places  # noqa: E402

POSTS = TypeAdapter(list[Post])
CLUES = TypeAdapter(list[Clue])
PHOTO_RESULTS = TypeAdapter(list[PhotoPlaceResult])
CANDIDATE_SETS = TypeAdapter(list[ProfileCandidateSet])
DEFAULT_FIXTURE = ROOT / "fixtures" / "photo_place_synthetic.json"


def _load_document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("evaluation_kind") != "synthetic_no_images":
        raise ValueError("photo-place evaluation accepts only synthetic_no_images fixtures")
    if value.get("annotation_kind") != "manual":
        raise ValueError("photo-place fixture must declare manual independent annotations")
    if not isinstance(value.get("cases"), list) or not isinstance(value.get("places"), list):
        raise ValueError("fixture must contain places and cases arrays")
    for case in value["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("posts"), list):
            raise ValueError("each synthetic case must contain posts")
        for post in case["posts"]:
            for image in post.get("images", []):
                if not isinstance(image, dict) or not str(image.get("url", "")).startswith(
                    "https://cdn.bsky.app/local-placeholder/"
                ):
                    raise ValueError("synthetic fixtures must use local-placeholder image URLs")
    return value


def _build_index(path: Path, records: list[dict[str, Any]]) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.executescript(
            "CREATE TABLE poi_place (place_id TEXT PRIMARY KEY, "
            "license_verified INTEGER NOT NULL, record_json TEXT NOT NULL);"
            "CREATE TABLE poi_alias (name_key TEXT NOT NULL, place_id TEXT NOT NULL, "
            "PRIMARY KEY(name_key, place_id));"
            "CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);"
        )
        for record in records:
            raw = json.dumps(record, ensure_ascii=False)
            sources = record.get("sources", [])
            licensed = bool(sources) and all(source.get("license_id") for source in sources)
            db.execute(
                "INSERT INTO poi_place VALUES (?, ?, ?)",
                (record["place_id"], int(licensed), raw),
            )
            names = [record["label"], *record.get("aliases", [])]
            keys = {key for name in names for key in place_name_keys(name)}
            db.executemany(
                "INSERT OR IGNORE INTO poi_alias VALUES (?, ?)",
                ((key, record["place_id"]) for key in keys),
            )


def _run_case(case: dict[str, Any], gazetteer: Gazetteer) -> dict[str, Any]:
    posts = POSTS.validate_python(case["posts"])
    clues = CLUES.validate_python(case["clues"])
    photo_results = infer_photo_places(posts, clues, gazetteer)
    sets = infer_owner_candidate_sets_with_web(
        posts,
        clues,
        [],
        gazetteer=gazetteer,
        photo_place_results=photo_results,
    )
    by_attr = {item.attribute: item for item in sets}
    residential = by_attr[ProfileAttribute.RESIDENTIAL_AREA]
    realtime = by_attr[ProfileAttribute.REALTIME_LOCATION]
    return {
        "photo_place_results": photo_results,
        "candidate_sets": sets,
        "status": photo_results[0].status.value if photo_results else "unknown",
        "place_ids": sorted(
            candidate.place_id
            for result in photo_results
            for candidate in result.candidates
        ),
        "location_claims": bool(residential.candidates or realtime.candidates),
        "location_claim_count": len(residential.candidates) + len(realtime.candidates),
        "residential_candidates": [candidate.value for candidate in residential.candidates],
        "realtime_candidates": [candidate.value for candidate in realtime.candidates],
    }


def _evaluate_deletions(
    case: dict[str, Any], gazetteer: Gazetteer, baseline: dict[str, Any]
) -> tuple[int, int]:
    deletions = case.get("delete_posts", [])
    if not deletions:
        return 0, 0
    if not baseline["location_claims"]:
        raise ValueError(f"case {case['id']} requires deletion checks but has no baseline claim")
    passed = 0
    for deleted_id in deletions:
        remaining_posts = [row for row in case["posts"] if row["post_id"] != deleted_id]
        remaining_clues = [row for row in case["clues"] if row["post_id"] != deleted_id]
        posts = POSTS.validate_python(remaining_posts)
        clues = CLUES.validate_python(remaining_clues)
        photo_results = infer_photo_places(posts, clues, gazetteer)
        candidate_sets = infer_owner_candidate_sets_with_web(
            posts,
            clues,
            [],
            gazetteer=gazetteer,
            photo_place_results=photo_results,
        )
        by_attr = {item.attribute: item for item in candidate_sets}
        lost = not (
            by_attr[ProfileAttribute.RESIDENTIAL_AREA].candidates
            or by_attr[ProfileAttribute.REALTIME_LOCATION].candidates
        )
        passed += int(lost)
    return passed, len(deletions)


def evaluate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Run the production inference functions against temporary synthetic POI data."""
    with tempfile.TemporaryDirectory(prefix="tkb-photo-place-eval-") as directory:
        index_path = Path(directory) / "places.sqlite3"
        _build_index(index_path, document["places"])
        gazetteer = Gazetteer(places_path=index_path)
        rows: list[dict[str, Any]] = []
        identifiable = 0
        candidate_covered = 0
        correct_candidate = 0
        unknown_predictions = 0
        appropriate_unknown = 0
        ambiguous_cases = 0
        ambiguous_single_assertions = 0
        forbidden_claim_cases = 0
        forbidden_claim_cases_with_any = 0
        forbidden_claims = 0
        deletion_passed = 0
        deletion_checks = 0

        for case in document["cases"]:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                raise ValueError("each case requires a string id")
            result = _run_case(case, gazetteer)
            truth_kind = case["truth_kind"]
            expected_ids = set(case.get("expected_place_ids", []))
            if truth_kind == "identifiable":
                identifiable += 1
                candidate_covered += int(bool(result["place_ids"]))
                correct_candidate += int(bool(expected_ids.intersection(result["place_ids"])))
            elif truth_kind not in {"ambiguous", "unknown"}:
                raise ValueError(f"unsupported truth_kind in {case['id']}: {truth_kind}")
            if result["status"] == "unknown":
                unknown_predictions += 1
                appropriate_unknown += int(truth_kind in {"ambiguous", "unknown"})
            if truth_kind == "ambiguous":
                ambiguous_cases += 1
                ambiguous_single_assertions += int(result["status"] == "candidate")
            if case.get("forbid_location_claim", False):
                forbidden_claim_cases += 1
                forbidden_claim_cases_with_any += int(result["location_claims"])
                forbidden_claims += result["location_claim_count"]
            dropped, checked = _evaluate_deletions(case, gazetteer, result)
            deletion_passed += dropped
            deletion_checks += checked
            rows.append(
                {
                    "id": case["id"],
                    "expected_truth_kind": truth_kind,
                    "predicted_status": result["status"],
                    "expected_place_ids": sorted(expected_ids),
                    "predicted_place_ids": result["place_ids"],
                    "location_claims": result["location_claims"],
                    "deletion_checks": checked,
                    "deletion_paths_dropped": dropped,
                }
            )

        return {
            "evaluation_kind": document["evaluation_kind"],
            "scope": "synthetic logic evaluation; not real-world geographic or image coverage",
            "metrics": {
                "identifiable_case_count": identifiable,
                "candidate_coverage": _ratio(candidate_covered, identifiable),
                "correct_candidate_rate": _ratio(correct_candidate, identifiable),
                "unknown_precision": _ratio(appropriate_unknown, unknown_predictions),
                "unknown_prediction_count": unknown_predictions,
                "ambiguous_single_assertion_rate": _ratio(
                    ambiguous_single_assertions, ambiguous_cases
                ),
                "forbidden_location_claim_count": forbidden_claims,
                "forbidden_location_claim_case_rate": _ratio(
                    forbidden_claim_cases_with_any, forbidden_claim_cases
                ),
                "deletion_path_drop_rate": _ratio(deletion_passed, deletion_checks),
                "deletion_path_drop_checks": deletion_checks,
            },
            "denominators": {
                "candidate_coverage": "identifiable truth cases; any candidate returned",
                "correct_candidate_rate": "identifiable truth cases; expected place_id in result",
                "unknown_precision": "predicted unknown cases; truth is ambiguous or unknown",
                "ambiguous_single_assertion_rate": "ambiguous truth cases; predicted candidate",
                "forbidden_location_claim_case_rate": (
                    "cases explicitly marked forbid_location_claim"
                ),
                "deletion_path_drop_rate": (
                    "declared single-post deletion checks from positive baseline cases"
                ),
            },
            "cases": rows,
        }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, nargs="?", default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    report = evaluate_document(_load_document(args.fixture))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
