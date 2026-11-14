"""Optional visual narrowing projected from the public 29 profile candidates."""

from collections.abc import Sequence
from functools import cache
from typing import Any

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    Post,
    ProfileAttribute,
    ProfileCandidate,
    ProfileCandidateSet,
    ProfileCandidateSetStatus,
)
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.walk_area import CENSUS_SOURCE, WALK_SOURCE, mesh_bounds, walk_area

REGION_LABEL = "1都3県"


def narrowing(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    profile_claims: Sequence[ProfileCandidateSet],
    gaz: Gazetteer,
) -> dict[str, Any] | None:
    """Build a display-only narrowing path from existing candidate sets.

    This never creates a profile value: the station and address must already be
    present in the 29-item result. Evidence IDs are retained for exclusion UI.
    """
    if not gaz.households:
        return None
    by_attribute = {claim.attribute: claim for claim in profile_claims}
    station_set = by_attribute.get(ProfileAttribute.HOME_NEAREST_STATION)
    walk = None
    if station_set is not None and station_set.status in {
        ProfileCandidateSetStatus.CANDIDATE,
        ProfileCandidateSetStatus.AMBIGUOUS,
    }:
        candidates = station_set.candidates
        selected = _station_for_walk(clues, posts, candidates)
        if selected is not None:
            candidate = selected
            evidence = [*candidate.evidence]
            station_indices = [
                item.clue_index
                for item in evidence
                if item.clue_index is not None and item.clue_index < len(clues)
            ]
            walk_area_result = walk_area(
                clues, posts, candidate.value, station_indices, gaz
            )
            if walk_area_result is not None:
                root_post_ids = [item.post_id for item in candidate.evidence if item.post_id]
                walk = {
                    "station": walk_area_result.station,
                    "minutes": walk_area_result.minutes,
                    "radius_m": walk_area_result.radius_m,
                    "center": list(walk_area_result.center),
                    "households": walk_area_result.households,
                    "meshes": [
                        {"code": m.code, "households": m.households, "share": round(m.share, 6)}
                        for m in walk_area_result.meshes
                        if round(m.share, 6) > 0
                    ],
                    "post_ids": list(dict.fromkeys([
                        *root_post_ids,
                        *_post_ids(clues, walk_area_result.clue_indices),
                    ])),
                }

    block_set = by_attribute.get(ProfileAttribute.RESIDENTIAL_AREA)
    block = _residential_block(block_set, clues)
    if walk is None and block is None:
        return None
    south, west, north, east = _region_bounds(tuple(sorted(gaz.households)))
    return {
        "region": {
            "label": REGION_LABEL,
            "households": sum(gaz.households.values()),
            "bounds": [south, west, north, east],
        },
        "walk": walk,
        "block": block,
        "sources": [CENSUS_SOURCE, *([WALK_SOURCE] if walk else [])],
    }


def _station_for_walk(
    clues: Sequence[Clue], posts: Sequence[Post], candidates: Sequence[ProfileCandidate]
) -> ProfileCandidate | None:
    """Choose only a candidate uniquely identified by a walk post."""
    from tkb_engine.walk_area import _walk_minutes

    matches = []
    for candidate in candidates:
        name = candidate.value.removesuffix("駅")
        if any(_walk_minutes(post.text, name) is not None for post in posts):
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    # Generic "家から駅まで徒歩N分" cannot disambiguate competing stations.
    if len(candidates) == 1 and matches:
        return candidates[0]
    return None


def _residential_block(candidate_set, clues: Sequence[Clue]) -> dict[str, Any] | None:
    if candidate_set is None or candidate_set.status is not ProfileCandidateSetStatus.CANDIDATE:
        return None
    by_index = {i: clue for i, clue in enumerate(clues)}
    eligible = []
    for candidate in candidate_set.candidates:
        indexes = {
            evidence.clue_index
            for evidence in candidate.evidence
            if evidence.clue_index is not None
        }
        if any(
            (clue := by_index.get(index)) is not None
            and clue.source in {ClueSource.OCR, ClueSource.VLM}
            and clue.type in {ClueType.CODE, ClueType.ADDRESS_TEXT}
            for index in indexes
        ):
            eligible.append((candidate, indexes))
    if len(eligible) != 1:
        return None
    candidate, indexes = eligible[0]
    return {
        "value": candidate.value,
        "post_ids": list(dict.fromkeys([
            *(item.post_id for item in candidate.evidence if item.post_id),
            *_post_ids(clues, sorted(indexes)),
        ])),
    }


def _post_ids(clues: Sequence[Clue], indices: Sequence[int]) -> list[str]:
    return list(dict.fromkeys(clues[i].post_id for i in indices if 0 <= i < len(clues)))


@cache
def _region_bounds(codes: tuple[str, ...]) -> tuple[float, float, float, float]:
    """Bounds of populated census meshes: (south, west, north, east)."""
    boxes = [mesh_bounds(c) for c in codes]
    return (
        round(min(b[0] for b in boxes), 6),
        round(min(b[1] for b in boxes), 6),
        round(max(b[2] for b in boxes), 6),
        round(max(b[3] for b in boxes), 6),
    )
