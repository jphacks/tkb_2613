"""Run local observation fixtures through the existing offline inference rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from candidate_evaluation import PROFILE_CANDIDATE_ATTRIBUTES, evaluate_candidate_sets  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

from tkb_common.schemas import Clue, Post, ProfileCandidateSet, ProfileItem  # noqa: E402
from tkb_engine import Conclusion, Gazetteer, infer  # noqa: E402
from tkb_engine.cross_post import infer_owner_claims  # noqa: E402
from tkb_engine.gazetteer import Knowledge  # noqa: E402
from tkb_engine.planner import simulate  # noqa: E402

DEFAULT_FIXTURE = ROOT / "fixtures" / "demo_observations.json"
POSTS = TypeAdapter(list[Post])
CLUES = TypeAdapter(list[Clue])
CANDIDATE_SETS = TypeAdapter(list[ProfileCandidateSet])


def _read_document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("posts"), list)
        or not isinstance(value.get("clues"), list)
    ):
        raise ValueError("fixture must contain posts and clues arrays")
    return value


def _truth_report(profile_claims: list[ProfileItem], truth: Any) -> dict[str, Any]:
    """Compare profile claims; provisional candidates are not called misses or false positives."""
    if not isinstance(truth, dict) or not isinstance(truth.get("claims"), list):
        return {"assessed": False, "reason": "no valid truth claims supplied"}
    truth_claims = truth["claims"]
    if any(
        not isinstance(claim, dict)
        or not isinstance(claim.get("attribute"), str)
        or not isinstance(claim.get("value"), str)
        for claim in truth_claims
    ):
        raise ValueError("truth claims must each have string attribute and value fields")
    status = truth.get("status", "unspecified")
    if status not in {"unspecified", "provisional", "confirmed"}:
        raise ValueError("truth status must be unspecified, provisional, or confirmed")
    expected = {(c["attribute"], c["value"]) for c in truth_claims}
    predicted = {(c.attribute.value, c.value) for c in profile_claims}
    complete_confirmed = truth.get("complete") is True and status == "confirmed"
    return {
        "assessed": True,
        "status": status,
        "complete": truth.get("complete") is True,
        "false_positives": _pairs(sorted(predicted - expected)) if complete_confirmed else None,
        "missed_expected_claims": (
            _pairs(sorted(expected - predicted)) if status == "confirmed" else None
        ),
        "provisional_candidates_not_in_inference": (
            _pairs(sorted(expected - predicted)) if status == "provisional" else None
        ),
    }


def _pairs(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"attribute": a, "value": v} for a, v in pairs]


def _serialize(conclusions: list[Conclusion], clues: list[Clue]) -> list[dict[str, Any]]:
    result = []
    for item in conclusions:
        evidence = []
        for index in item.clue_indices:
            if index < 0 or index >= len(clues):
                raise ValueError(f"inference returned invalid clue index {index}")
            clue = clues[index]
            evidence.append(
                {
                    "clue_index": index,
                    "post_id": clue.post_id,
                    "type": clue.type.value,
                    "image_index": clue.image_index,
                    "region": list(clue.region) if clue.region is not None else None,
                    "source": clue.source.value,
                }
            )
        result.append(
            {
                "rule": item.rule,
                "attribute": item.attribute,
                "value": item.value,
                "evidence": evidence,
            }
        )
    return result


def _serialize_profile_claims(claims: list[ProfileItem], clues: list[Clue]) -> list[dict[str, Any]]:
    """Keep alternative evidence paths separate and resolve each clue reference in place."""
    results: list[dict[str, Any]] = []
    for claim in claims:
        paths = []
        for path in claim.evidence_paths:
            references = []
            for reference in path.evidence:
                evidence: dict[str, Any] = {
                    "source": reference.source.value,
                    "post_id": reference.post_id,
                    "required": reference.required,
                }
                if reference.clue_index is not None:
                    index = reference.clue_index
                    if index < 0 or index >= len(clues):
                        raise ValueError(f"profile inference returned invalid clue index {index}")
                    clue = clues[index]
                    if clue.post_id != reference.post_id:
                        raise ValueError("profile inference clue reference does not match its post")
                    evidence.update(
                        {
                            "clue_index": index,
                            "type": clue.type.value,
                            "image_index": clue.image_index,
                            "region": list(clue.region) if clue.region is not None else None,
                        }
                    )
                elif reference.image_index is not None:
                    evidence["image_index"] = reference.image_index
                references.append(evidence)
            paths.append({"confidence": path.confidence, "evidence": references})
        results.append(
            {
                "attribute": claim.attribute.value,
                "value": claim.value,
                "confidence": claim.confidence,
                "status": claim.status.value,
                "evidence_paths": paths,
            }
        )
    return results


def build_report(
    document: dict[str, Any],
    excluded: list[str],
    gaz: Gazetteer,
    truth: Any = None,
    table_availability: dict[str, bool] | None = None,
    candidate_sets: Any = None,
    provenance_scope: str = "all",
) -> dict[str, Any]:
    if candidate_sets is None:
        candidate_sets = document.get("candidate_sets")
    if candidate_sets is not None:
        if isinstance(candidate_sets, dict):
            candidate_sets = candidate_sets.get(
                "profile_claims", candidate_sets.get("candidate_sets")
            )
        if not isinstance(candidate_sets, list):
            raise ValueError("candidate sets must be an array")
        if any(
            not isinstance(row, dict) or not isinstance(row.get("attribute"), str)
            for row in candidate_sets
        ):
            raise ValueError("candidate sets require string attribute fields")
        candidate_attributes = [row["attribute"] for row in candidate_sets]
        if (
            len(candidate_sets) != len(PROFILE_CANDIDATE_ATTRIBUTES)
            or set(candidate_attributes) != PROFILE_CANDIDATE_ATTRIBUTES
        ):
            raise ValueError(
                "candidate sets must contain exactly 24 unique attributes excluding home_room"
            )
        parsed_candidate_sets = CANDIDATE_SETS.validate_python(candidate_sets)
        candidate_sets = [row.model_dump(mode="json") for row in parsed_candidate_sets]

    # Local fixture image paths are presentation metadata, not part of the inference Post type.
    post_rows = [
        {
            **row,
            "images": [
                {k: v for k, v in image.items() if k != "local_file"} for image in row["images"]
            ],
        }
        for row in document["posts"]
    ]
    posts = POSTS.validate_python(post_rows)
    clues = CLUES.validate_python(document["clues"])
    known_posts = {post.post_id for post in posts}
    unknown = sorted(set(excluded) - known_posts)
    if unknown:
        raise ValueError("excluded post id is not present in fixture")
    if any(clue.post_id not in known_posts for clue in clues):
        raise ValueError("fixture contains a clue whose post_id is absent from posts")

    profile_before = infer_owner_claims(posts, clues, gazetteer=gaz)
    before = infer(clues, posts, gaz)
    simulation = simulate(clues, posts, gaz, excluded)
    after_profile_posts = [post for post in posts if post.post_id not in set(excluded)]
    after_profile_clues = [clue for clue in clues if clue.post_id not in set(excluded)]
    # Re-run the claim rules on the reduced data: exclusion can make a different bridge/rule win.
    profile_after = infer_owner_claims(after_profile_posts, after_profile_clues, gazetteer=gaz)
    if truth is None:
        truth = document.get("truth")
    annotation_kind = document.get("annotation_kind", "fixture")
    if annotation_kind not in {"fixture", "manual", "detector"}:
        raise ValueError("annotation_kind must be fixture, manual, or detector")
    available = table_availability or {
        "stations": bool(gaz.stations),
        "postal": bool(gaz.postal),
        "muni_mesh": bool(gaz.muni_meshes),
        "schools": bool(gaz.schools),
    }
    geographic_tables_available = all(
        available.get(key, False) for key in ("stations", "postal", "muni_mesh")
    )
    if annotation_kind == "manual":
        evaluation_track = "manual_annotation_rule_evaluation"
    elif annotation_kind == "detector":
        evaluation_track = "ocr_vlm_end_to_end_evaluation"
    else:
        evaluation_track = "fixture_source_unspecified"
    candidate_truth_evaluation = (
        evaluate_candidate_sets(
            candidate_sets,
            truth,
            post_ids=known_posts,
            post_images={post.post_id: {image.index for image in post.images} for post in posts},
            clues=[clue.model_dump(mode="json") for clue in clues],
            web_fact_ids={
                row["id"]
                for row in document.get("web_facts", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            },
            provenance_scope=provenance_scope,
        )
        if candidate_sets is not None
        else {"assessed": False, "reason": "no candidate sets supplied"}
    )
    return {
        "mode": "offline_fixture_inference",
        "annotation_kind": annotation_kind,
        "evaluation_track": evaluation_track,
        "geographic_tables": available,
        "excluded_post_ids": list(dict.fromkeys(excluded)),
        "claims": {
            "profile_inference": {
                "before": _serialize_profile_claims(profile_before, clues),
                "after": _serialize_profile_claims(profile_after, after_profile_clues),
            },
            "legacy_conclusions": {
                "before": _serialize(before, clues),
                "after": _serialize(simulation.after, simulation.after_clues),
                "broken_attributes": simulation.broken,
            },
        },
        "truth_evaluation": {
            "profile_inference_before": _truth_report(profile_before, truth),
            "profile_inference_after": _truth_report(profile_after, truth),
        },
        "candidate_set_truth_evaluation": candidate_truth_evaluation,
        "candidate_set_provenance_scope": provenance_scope,
        "notes": [
            "Inference and hypothetical exclusion use local rules only; "
            "no account or model is contacted.",
            "Evidence clue_index refers to the matching clue array; source text is omitted.",
            "False positives require a complete, confirmed truth set.",
            "Truth comparison uses profile_inference claims; "
            "legacy conclusions are shown separately.",
            *(
                ["Clues are manually annotated and are not OCR/VLM results."]
                if annotation_kind == "manual"
                else []
            ),
            *(
                [
                    "Clues come from OCR/VLM extraction; this track includes detector "
                    "and inference behavior."
                ]
                if annotation_kind == "detector"
                else []
            ),
            *(
                [
                    "Observation provenance is unspecified; do not interpret this as manual-only "
                    "or OCR/VLM end-to-end evaluation."
                ]
                if annotation_kind == "fixture"
                else []
            ),
            *(
                []
                if geographic_tables_available
                else [
                    "Geographic public tables are unavailable; "
                    "table-dependent inferences may be absent."
                ]
            ),
        ],
    }


def _gazetteer() -> tuple[Gazetteer, dict[str, bool]]:
    data = ROOT.parent / "data" / "processed"
    available = {
        "stations": (data / "stations.parquet").is_file(),
        "postal": (data / "postal.parquet").is_file(),
        "muni_mesh": (data / "muni_mesh.parquet").is_file(),
        "schools": (data / "schools.parquet").is_file(),
    }
    if all(available[key] for key in ("stations", "postal", "muni_mesh")):
        return Gazetteer.load(data), available
    # Keep non-geographic inference useful when public tables have not been prepared.
    return Gazetteer(knowledge=Knowledge.load()), available


def _output_path(path: Path) -> Path:
    target = path.resolve()
    local_dir = (ROOT / "local").resolve()
    if target != local_dir and local_dir not in target.parents:
        raise ValueError("report output must be inside eval/local/ (ignored local data)")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--exclude", action="append", default=[], help="post_id to hypothetically omit"
    )
    parser.add_argument(
        "--truth", type=Path, help="separate truth JSON with complete and claims fields"
    )
    parser.add_argument(
        "--candidate-sets",
        type=Path,
        help="JSON array of ProfileCandidateSet values (or report object with profile_claims)",
    )
    parser.add_argument(
        "--provenance-scope",
        choices=("all", "direct_disclosure", "combined_inference", "unclassified"),
        default="all",
        help="score candidates with evidence paths in this provenance scope",
    )
    parser.add_argument(
        "--output", type=Path, help="write JSON report under eval/local/ instead of stdout"
    )
    args = parser.parse_args(argv)
    try:
        document = _read_document(args.fixture)
        truth = json.loads(args.truth.read_text(encoding="utf-8")) if args.truth else None
        candidate_sets = (
            json.loads(args.candidate_sets.read_text(encoding="utf-8"))
            if args.candidate_sets
            else None
        )
        gazetteer, table_availability = _gazetteer()
        report = build_report(
            document,
            args.exclude,
            gazetteer,
            truth,
            table_availability,
            candidate_sets,
            args.provenance_scope,
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            _output_path(args.output).write_text(serialized, encoding="utf-8")
        else:
            sys.stdout.write(serialized)
    except (OSError, ValueError, json.JSONDecodeError):
        # Validation exceptions can contain whole input rows; keep them out of terminal logs.
        print(
            "mock inference report failed: invalid input or unavailable local data",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
