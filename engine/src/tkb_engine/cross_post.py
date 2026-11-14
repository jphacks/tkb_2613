"""Conservative claim paths for residential area, commute station, and employer evidence."""

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from itertools import combinations

from tkb_common.place_names import place_name_keys
from tkb_common.schemas import (
    ClaimAssessment,
    Clue,
    ClueSource,
    ClueType,
    EvidencePathProvenance,
    EvidenceScope,
    EvidenceSource,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceRelation,
    PhotoPlaceResult,
    PhotoPlaceStatus,
    PhotoPlaceType,
    Post,
    ProfileAttribute,
    ProfileCandidate,
    ProfileCandidateSet,
    ProfileCandidateSetStatus,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileRelation,
    ProfileRelationEndpoint,
    ProfileRelationEndpointKind,
    ProfileRelationKind,
    ProfileStatus,
    WebFact,
    WebSourceKind,
    WebVerificationStatus,
)
from tkb_engine.child_school import BRIDGE_PREFIX as CHILD_SCHOOL_BRIDGE
from tkb_engine.child_school import child_school_facts
from tkb_engine.cross_post_facts import (
    CrossPostFact,
    FactRole,
)
from tkb_engine.cross_post_facts import (
    forbidden_context as _forbidden_context,
)
from tkb_engine.cross_post_facts import (
    is_distinctive_bridge as _is_distinctive_bridge,
)
from tkb_engine.cross_post_facts import (
    matching_text_clue as _matching_text_clue,
)
from tkb_engine.cross_post_facts import (
    normalize_bridge as _normalize_bridge,
)
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.open_data import infer_registry_employer_claim, shelter_home_facts
from tkb_engine.open_data_bus import bus_stop_home_facts
from tkb_engine.open_data_school import add_school_district_residence
from tkb_engine.rules import WEEKDAYS, Conclusion, infer, timestamps_usable


def infer_cross_post_claim(
    attribute: ProfileAttribute,
    facts: list[CrossPostFact],
) -> ProfileItem | None:
    """Build only unambiguous AND paths spanning at least two independent posts.

    Each successful path needs one explicit owner-relation fact and one value fact, in
    different posts, joined by the same explicit bridge. Any competing value invalidates the
    claim instead of choosing one. Confidence is the weakest fact on the AND path.
    """
    if attribute not in {
        ProfileAttribute.RESIDENTIAL_AREA,
        ProfileAttribute.REGULAR_STATION,
        ProfileAttribute.HOME_NEAREST_STATION,
        ProfileAttribute.CHILD_SCHOOL,
    }:
        raise ValueError("cross-post gate is only defined for supported cross-post attributes")
    expected_bridge = {
        ProfileAttribute.RESIDENTIAL_AREA: "home:",
        ProfileAttribute.REGULAR_STATION: "regular_station:",
        ProfileAttribute.HOME_NEAREST_STATION: "home_station:",
        ProfileAttribute.CHILD_SCHOOL: CHILD_SCHOOL_BRIDGE,
    }[attribute]
    eligible = [
        f
        for f in facts
        if f.value.strip()
        and f.bridge_id
        and f.bridge_id.startswith(expected_bridge)
        and not _forbidden_context(f.context)
    ]
    anchors = [
        f for f in eligible if f.role is FactRole.OWNER_RELATION and f.owner_relation_explicit
    ]
    values = [f for f in eligible if f.role is FactRole.SPECIFIC_VALUE]
    bridges = [f for f in eligible if f.role is FactRole.BRIDGE]
    paths: list[list[CrossPostFact]] = []
    candidates: dict[str, str] = {}
    for anchor in anchors:
        for value_fact in values:
            if anchor.source != "profile_text" and anchor.post_id == value_fact.post_id:
                continue
            if anchor.bridge_id != value_fact.bridge_id:
                continue
            key = value_fact.value.strip().lower()
            candidates[key] = value_fact.value.strip()
            if anchor.post_id is not None and value_fact.post_id is not None:
                paths.append([anchor, value_fact])
            else:
                required_post_ids = {
                    f.post_id for f in (anchor, value_fact) if f.post_id is not None
                }
                bridge_posts = [
                    f
                    for f in bridges
                    if f.bridge_id == anchor.bridge_id
                    and f.post_id is not None
                    and f.post_id not in required_post_ids
                ]
                needed = max(1, 2 - len(required_post_ids))
                for bridge_group in combinations(bridge_posts, needed):
                    path = [anchor, value_fact, *bridge_group]
                    if len({f.post_id for f in path if f.post_id is not None}) >= 2:
                        paths.append(path)
    if not paths or len(candidates) != 1:
        return None

    # Preserve alternative independent paths. Deleting a post then means removing paths that
    # cite it; the claim survives only if at least one complete path remains.
    paths_by_signature: dict[tuple[tuple[object, ...], ...], list[CrossPostFact]] = {}
    for path in paths:
        signature = tuple(
            sorted(
                (
                    f.source,
                    f.post_id or "",
                    f.clue_index if f.clue_index is not None else -1,
                    f.role.value,
                    f.bridge_id or "",
                    f.value,
                    f.excerpt,
                )
                for f in path
            )
        )
        paths_by_signature[signature] = path
    evidence_paths = [
        ProfileEvidencePath(
            evidence=[
                reference
                for fact in path
                for reference in [
                    ProfileEvidence(
                        post_id=fact.post_id if fact.source != "profile_text" else None,
                        clue_index=fact.clue_index,
                        required=True,
                        source=fact.source if fact.clue_index is None else "clue",
                        excerpt=fact.excerpt if fact.clue_index is None else None,
                    ),
                    *fact.related_evidence,
                ]
            ],
            confidence=min(f.confidence for f in path),
            provenance=EvidencePathProvenance.COMBINED_INFERENCE,
        )
        for path in paths_by_signature.values()
    ]
    flat_evidence = [e for path in evidence_paths for e in path.evidence]
    confidence = max(path.confidence for path in evidence_paths)
    if confidence < 0.5:
        return None
    value = next(iter(candidates.values()))
    return ProfileItem(
        attribute=attribute,
        value=value,
        confidence=confidence,
        status=ProfileStatus.WEAK,
        evidence=flat_evidence,
        evidence_paths=evidence_paths,
        assessment=ClaimAssessment(
            minimal_scope=EvidenceScope.BLUESKY,
            harm_status="unknown",
        ),
    )


def infer_cross_post_candidates(
    attribute: ProfileAttribute,
    facts: list[CrossPostFact],
) -> list[ProfileItem]:
    """Return separately grounded values for an attribute without choosing by order."""
    if attribute not in {
        ProfileAttribute.RESIDENTIAL_AREA,
        ProfileAttribute.REGULAR_STATION,
        ProfileAttribute.HOME_NEAREST_STATION,
        ProfileAttribute.CHILD_SCHOOL,
    }:
        raise ValueError("cross-post gate is only defined for supported cross-post attributes")
    expected_bridge = {
        ProfileAttribute.RESIDENTIAL_AREA: "home:",
        ProfileAttribute.REGULAR_STATION: "regular_station:",
        ProfileAttribute.HOME_NEAREST_STATION: "home_station:",
        ProfileAttribute.CHILD_SCHOOL: CHILD_SCHOOL_BRIDGE,
    }[attribute]
    eligible = [
        fact
        for fact in facts
        if fact.value.strip()
        and fact.bridge_id
        and fact.bridge_id.startswith(expected_bridge)
        and not _forbidden_context(fact.context)
    ]
    anchors = [
        fact
        for fact in eligible
        if fact.role is FactRole.OWNER_RELATION and fact.owner_relation_explicit
    ]
    values = [fact for fact in eligible if fact.role is FactRole.SPECIFIC_VALUE]
    bridge_facts = [fact for fact in eligible if fact.role is FactRole.BRIDGE]
    paths_by_value: dict[str, list[list[CrossPostFact]]] = {}
    values_by_key: dict[str, str] = {}
    for anchor in anchors:
        for value_fact in values:
            if anchor.source != "profile_text" and anchor.post_id == value_fact.post_id:
                continue
            if anchor.bridge_id != value_fact.bridge_id:
                continue
            normalized = unicodedata.normalize("NFKC", value_fact.value).lower().strip()
            values_by_key.setdefault(normalized, value_fact.value.strip())
            if anchor.post_id is not None and value_fact.post_id is not None:
                paths_by_value.setdefault(normalized, []).append([anchor, value_fact])
                continue
            required_post_ids = {
                fact.post_id for fact in (anchor, value_fact) if fact.post_id is not None
            }
            bridge_posts = [
                fact
                for fact in bridge_facts
                if fact.bridge_id == anchor.bridge_id
                and fact.post_id is not None
                and fact.post_id not in required_post_ids
            ]
            needed = max(1, 2 - len(required_post_ids))
            for bridge_group in combinations(bridge_posts, needed):
                path = [anchor, value_fact, *bridge_group]
                if len({fact.post_id for fact in path if fact.post_id is not None}) >= 2:
                    paths_by_value.setdefault(normalized, []).append(path)

    results: list[ProfileItem] = []
    for normalized, paths in paths_by_value.items():
        if not paths:
            continue
        unique_paths: dict[tuple[tuple[object, ...], ...], list[CrossPostFact]] = {}
        for path in paths:
            signature = tuple(
                sorted(
                    (
                        fact.source,
                        fact.post_id or "",
                        fact.clue_index if fact.clue_index is not None else -1,
                        fact.role.value,
                        fact.bridge_id or "",
                        fact.value,
                        fact.excerpt,
                    )
                    for fact in path
                )
            )
            unique_paths[signature] = path
        evidence_paths = [
            ProfileEvidencePath(
                evidence=[
                    ref
                    for fact in path
                    for ref in [
                        ProfileEvidence(
                            post_id=fact.post_id if fact.source != "profile_text" else None,
                            clue_index=fact.clue_index,
                            required=True,
                            source=fact.source if fact.clue_index is None else "clue",
                            excerpt=fact.excerpt if fact.clue_index is None else None,
                        ),
                        *fact.related_evidence,
                    ]
                ],
                confidence=min(fact.confidence for fact in path),
                provenance=EvidencePathProvenance.COMBINED_INFERENCE,
            )
            for path in unique_paths.values()
        ]
        confidence = max(path.confidence for path in evidence_paths)
        if confidence < 0.5:
            continue
        results.append(
            ProfileItem(
                attribute=attribute,
                value=values_by_key[normalized],
                confidence=confidence,
                status=ProfileStatus.WEAK,
                evidence=[ref for path in evidence_paths for ref in path.evidence],
                evidence_paths=evidence_paths,
                assessment=ClaimAssessment(
                    minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                ),
            )
        )
    return results


def infer_child_school_claims(
    posts: list[Post], clues: list[Clue], gazetteer: Gazetteer
) -> list[ProfileItem]:
    """Infer child school candidates only through the explicit cross-post bridge."""
    claims = infer_cross_post_candidates(
        ProfileAttribute.CHILD_SCHOOL, child_school_facts(posts, clues, gazetteer)
    )
    return [
        claim.model_copy(
            update={
                "assessment": ClaimAssessment(
                    minimal_scope=EvidenceScope.BLUESKY,
                    harm_status="prerequisites_unmet",
                    harm_scenario="子どもの通う学校がわかると、登下校の時間や場所で子どもに近づく、"
                    "学校を名乗って保護者をだますなどの材料になりうる",
                    harm_prerequisites=[
                        "子どもを識別できる情報が別途得られる",
                        "攻撃者がその情報を悪用する",
                    ],
                )
            }
        )
        for claim in claims
    ]


def _realtime_path_observed_at(
    path: ProfileEvidencePath, posts_by_id: Mapping[str, Post]
) -> datetime | None:
    """Return the newest timestamp cited by one complete realtime evidence path."""
    timestamps = [
        posts_by_id[post_id].created_at
        for post_id in {
            reference.post_id
            for reference in path.evidence
            if reference.post_id is not None and reference.post_id in posts_by_id
        }
    ]
    if not timestamps:
        return None
    return max(timestamps)


def evaluate_profile_candidates(
    claims: Sequence[ProfileItem],
    posts: Sequence[Post],
    conflict_reasons: Mapping[ProfileAttribute, str] | None = None,
    clues: Sequence[Clue] = (),
) -> list[ProfileCandidateSet]:
    """Return all 29 diagnosed attributes as bounded, grounded candidate sets.

    A singleton is explicitly a candidate, not a resolved truth. A weak leader keeps up
    to three evidence-sufficient candidates regardless of score gap. A found leader keeps
    same-grade contenders within 0.15 score points. Scores are provisional rule scores.
    """
    attributes = [
        attribute for attribute in ProfileAttribute if attribute is not ProfileAttribute.HOME_ROOM
    ]
    grouped: dict[ProfileAttribute, dict[str, ProfileItem]] = {
        attribute: {} for attribute in attributes
    }
    post_by_id = {post.post_id: post for post in posts}
    for claim in claims:
        if (
            claim.attribute not in grouped
            or claim.status is ProfileStatus.UNKNOWN
            or not claim.value
            or not claim.evidence_paths
        ):
            continue
        normalized = unicodedata.normalize("NFKC", claim.value).lower().strip()
        current = grouped[claim.attribute].get(normalized)
        if current is None:
            grouped[claim.attribute][normalized] = claim
        else:
            paths = [*current.evidence_paths, *claim.evidence_paths]
            unique_paths = {
                (
                    path.provenance.value,
                    tuple(
                        (
                            reference.source.value,
                            reference.post_id or "",
                            reference.clue_index,
                            reference.web_fact_id or "",
                            reference.excerpt or "",
                        )
                        for reference in path.evidence
                    ),
                ): path
                for path in paths
            }
            kept_paths = list(unique_paths.values())
            stronger = claim if claim.confidence > current.confidence else current
            grouped[claim.attribute][normalized] = stronger.model_copy(
                update={
                    "confidence": max(current.confidence, claim.confidence),
                    "status": (
                        ProfileStatus.FOUND
                        if ProfileStatus.FOUND in {current.status, claim.status}
                        else ProfileStatus.WEAK
                    ),
                    "evidence_paths": kept_paths,
                    "evidence": [reference for path in kept_paths for reference in path.evidence],
                }
            )

    result: list[ProfileCandidateSet] = []
    counter_by_attribute_value, conflicts_by_attribute = _collect_counter_evidence(posts, clues)
    for attribute in attributes:
        conflict_reason = (conflict_reasons or {}).get(attribute)
        if conflict_reason:
            conflicting_evidence = conflicts_by_attribute.get(attribute, [])
            result.append(
                ProfileCandidateSet(
                    attribute=attribute,
                    status=ProfileCandidateSetStatus.CONFLICT
                    if conflicting_evidence
                    else ProfileCandidateSetStatus.UNKNOWN,
                    candidates=[],
                    candidate_pool=[],
                    conflicting_evidence=conflicting_evidence,
                    reason=conflict_reason if conflicting_evidence else "conflict_not_evidenced",
                )
            )
            continue
        ranked = sorted(
            grouped[attribute].values(),
            key=lambda claim: (
                -claim.confidence,
                unicodedata.normalize("NFKC", claim.value or "").lower(),
            ),
        )
        if not ranked:
            result.append(
                ProfileCandidateSet(
                    attribute=attribute,
                    status=ProfileCandidateSetStatus.UNKNOWN,
                    candidates=[],
                    candidate_pool=[],
                    conflicting_evidence=conflicts_by_attribute.get(attribute, []),
                    reason="explicit_negation"
                    if conflicts_by_attribute.get(attribute)
                    else "no_grounded_rule",
                )
            )
            continue
        # If evidence grades differ, or the runner-up is materially weaker, show only the
        # strongest value while preserving its candidate (not found-fact) status.
        strongest = ranked[0]

        def make_candidate(
            claim: ProfileItem, rank: int, candidate_attribute: ProfileAttribute = attribute
        ) -> ProfileCandidate:
            observed_at = None
            if candidate_attribute is ProfileAttribute.REALTIME_LOCATION:
                observed_at = max(
                    (
                        timestamp
                        for path in claim.evidence_paths
                        if (timestamp := _realtime_path_observed_at(path, post_by_id)) is not None
                    ),
                    default=None,
                )
            counter_evidence = counter_by_attribute_value.get(
                (
                    candidate_attribute,
                    unicodedata.normalize("NFKC", claim.value or "").lower().strip(),
                ),
                [],
            )
            return ProfileCandidate(
                rank=rank,
                value=claim.value or "",
                confidence=claim.confidence,
                status=claim.status,
                evidence=claim.evidence,
                evidence_paths=claim.evidence_paths,
                assessment=claim.assessment,
                observed_at=observed_at,
                counter_evidence=counter_evidence,
            )

        candidate_pool = [make_candidate(claim, rank) for rank, claim in enumerate(ranked, start=1)]
        if strongest.status is ProfileStatus.WEAK:
            eligible = [
                candidate for candidate in candidate_pool if candidate.status is ProfileStatus.WEAK
            ]
        else:
            eligible = [
                candidate
                for candidate in candidate_pool
                if candidate.status is strongest.status
                and strongest.confidence - candidate.confidence <= 0.15
            ]
        candidates = eligible[:3]
        result.append(
            ProfileCandidateSet(
                attribute=attribute,
                status=ProfileCandidateSetStatus.AMBIGUOUS
                if len(candidates) > 1
                else ProfileCandidateSetStatus.CANDIDATE,
                candidates=candidates,
                candidate_pool=candidate_pool,
                conflicting_evidence=conflicts_by_attribute.get(attribute, []),
                reason=None,
            )
        )
    return result


def _collect_counter_evidence(
    posts: Sequence[Post], clues: Sequence[Clue]
) -> tuple[
    dict[tuple[ProfileAttribute, str], list[ProfileEvidence]],
    dict[ProfileAttribute, list[ProfileEvidence]],
]:
    """Retain evidence for explicit denials even when they disqualify a candidate."""
    by_value: dict[tuple[ProfileAttribute, str], list[ProfileEvidence]] = {}
    by_attribute: dict[ProfileAttribute, list[ProfileEvidence]] = {}
    for post in posts:
        for attribute, (pattern, allowed_types) in _EXPLICIT_CLAIM_RULES.items():
            # Re-run the same capture rule with an explicit denial ending so the
            # value remains bounded to the claim clause (and never a later name).
            denial_pattern = re.compile(
                pattern.pattern.replace(
                    "(?:です|だ|$)",
                    "(?:です|だ)?(?:ではありませんでした|ではありません|ではなかった|ではない|じゃない|ではなく|では無い)",
                )
            )
            match = denial_pattern.search(post.text)
            if match is None or not _is_negated_claim(post.text, match.end("value")):
                continue
            captured_value = match.groupdict().get("value")
            if captured_value is None:
                continue
            captured_value = captured_value.removesuffix("です").removesuffix("だ").strip()
            for index, clue in enumerate(clues):
                if (
                    clue.post_id != post.post_id
                    or clue.type not in allowed_types
                    or clue.confidence < 0.5
                    or _normalize_bridge(clue.value) != _normalize_bridge(captured_value)
                ):
                    continue
                refs = [
                    ProfileEvidence(
                        post_id=post.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=post.post_id, clue_index=index, required=True, source="clue"
                    ),
                ]
                key = (attribute, unicodedata.normalize("NFKC", clue.value).lower().strip())
                by_value.setdefault(key, []).extend(refs)
                by_attribute.setdefault(attribute, []).extend(refs)
    return by_value, by_attribute


def recalculate_after_deletion(item: ProfileItem, deleted_post_ids: set[str]) -> ProfileItem | None:
    """Keep only complete alternative proof paths that survive post deletion."""
    surviving = [
        path
        for path in item.evidence_paths
        if not any(reference.post_id in deleted_post_ids for reference in path.evidence)
    ]
    if not surviving:
        return None
    confidence = max(path.confidence for path in surviving)
    if confidence < 0.5:
        return None
    status = item.status
    if status is ProfileStatus.FOUND and all(
        path.provenance is EvidencePathProvenance.COMBINED_INFERENCE for path in surviving
    ):
        status = ProfileStatus.WEAK
    return item.model_copy(
        update={
            "evidence_paths": surviving,
            "evidence": [e for path in surviving for e in path.evidence],
            "confidence": confidence,
            "status": status,
            "assessment": item.assessment.model_copy(
                update={"minimal_scope": _minimal_scope(surviving)}
            ),
        }
    )


def claims_after_deletion(
    claims: Sequence[ProfileItem], deleted_post_ids: Collection[str]
) -> list[ProfileItem]:
    """Recalculate legacy ProfileItem claims after excluding posts.

    Candidate-set restoration uses ``recalculate_profile_candidate_sets`` instead;
    this helper remains for legacy conclusion and Threads response contracts.
    """
    deleted = set(deleted_post_ids)
    if not deleted:
        return list(claims)
    kept: list[ProfileItem] = []
    for claim in claims:
        if claim.evidence_paths and claim.status is not ProfileStatus.UNKNOWN:
            after = recalculate_after_deletion(claim, deleted)
            if after is not None:
                kept.append(after)
        elif not any(reference.post_id in deleted for reference in claim.evidence):
            kept.append(claim)
    return kept


PROFILE_PLAN_MAX_POSTS = 3


def plan_profile_claim_deletion(claims: Sequence[ProfileItem], posts: Sequence[Post]) -> list[str]:
    """Choose up to max_posts that remove the most currently supported claims.

    Evidence within a path is AND and paths are OR. A claim is lost only when every
    path has at least one deleted post. Exact combinations are checked because a claim
    with alternative paths may have no single post that weakens it immediately.
    Ties prefer fewer posts and then the original diagnosed post order.
    """
    if not claims or not posts:
        return []

    post_order = list(dict.fromkeys(post.post_id for post in posts))
    post_indexes = {post_id: index for index, post_id in enumerate(post_order)}
    candidate_indexes = sorted(
        {
            post_indexes[reference.post_id]
            for claim in claims
            for path in claim.evidence_paths
            for reference in path.evidence
            if reference.post_id in post_indexes
        }
    )
    if not candidate_indexes:
        return []

    # For each claim, map each diagnosed post to the evidence paths that mention it.
    # A claim is broken when the selected posts collectively invalidate every
    # sufficiently confident path. This keeps subset scoring to at most 3 lookups.
    path_masks_by_claim: list[tuple[int, dict[int, int]]] = []
    for claim in claims:
        eligible_paths = [path for path in claim.evidence_paths if path.confidence >= 0.5]
        if not eligible_paths:
            continue
        all_path_bits = (1 << len(eligible_paths)) - 1
        paths_by_post: dict[int, int] = {}
        for path_index, path in enumerate(eligible_paths):
            path_bit = 1 << path_index
            for reference in path.evidence:
                if reference.post_id in post_indexes:
                    post_index = post_indexes[reference.post_id]
                    paths_by_post[post_index] = paths_by_post.get(post_index, 0) | path_bit
        path_masks_by_claim.append((all_path_bits, paths_by_post))
    if not path_masks_by_claim:
        return []

    limit = min(PROFILE_PLAN_MAX_POSTS, len(candidate_indexes))
    best_score: tuple[int, int, tuple[int, ...]] | None = None
    best_indexes: tuple[int, ...] = ()
    for count in range(1, limit + 1):
        for selected_indexes in combinations(candidate_indexes, count):
            broken_count = 0
            for all_path_bits, paths_by_post in path_masks_by_claim:
                broken_path_bits = 0
                for index in selected_indexes:
                    broken_path_bits |= paths_by_post.get(index, 0)
                broken_count += broken_path_bits == all_path_bits
                if broken_count == len(path_masks_by_claim):
                    break
            if not broken_count:
                continue
            score = (-broken_count, count, selected_indexes)
            if best_score is None or score < best_score:
                best_score, best_indexes = score, selected_indexes
    return [post_order[index] for index in best_indexes]


def plan_profile_candidate_deletion(
    candidate_sets: Sequence[ProfileCandidateSet], posts: Sequence[Post]
) -> list[str]:
    """Prefer attributes that become unsupported, then reduce remaining candidates.

    Removing a currently top-ranked value while another grounded value survives is a rank
    change, not a broken attribute. All values in the full pool are re-evaluated per subset.
    Ties prefer fewer posts and then original post order.
    """
    eligible_sets = [
        candidate_set for candidate_set in candidate_sets if candidate_set.candidate_pool
    ]
    if not eligible_sets or not posts:
        return []
    post_order = list(dict.fromkeys(post.post_id for post in posts))
    candidate_indexes = sorted(
        {
            post_order.index(reference.post_id)
            for candidate_set in eligible_sets
            for candidate in candidate_set.candidate_pool
            for path in candidate.evidence_paths
            for reference in path.evidence
            if reference.post_id in post_order
        }
    )
    if not candidate_indexes:
        return []

    best_score: tuple[int, int, int, tuple[int, ...]] | None = None
    best_indexes: tuple[int, ...] = ()
    limit = min(PROFILE_PLAN_MAX_POSTS, len(candidate_indexes))
    for count in range(1, limit + 1):
        for selected in combinations(candidate_indexes, count):
            deleted = {post_order[index] for index in selected}
            collapsed_attributes = 0
            reduced_candidates = 0
            for candidate_set in eligible_sets:
                surviving_count = 0
                for candidate in candidate_set.candidate_pool:
                    survives = any(
                        path.confidence >= 0.5
                        and not any(reference.post_id in deleted for reference in path.evidence)
                        for path in candidate.evidence_paths
                    )
                    surviving_count += survives
                if surviving_count == 0:
                    collapsed_attributes += 1
                reduced_candidates += len(candidate_set.candidate_pool) - surviving_count
            if not reduced_candidates:
                continue
            score = (-collapsed_attributes, -reduced_candidates, count, selected)
            if best_score is None or score < best_score:
                best_score, best_indexes = score, selected
    return [post_order[index] for index in best_indexes]


def recalculate_profile_candidate_sets(
    candidate_sets: Sequence[ProfileCandidateSet],
    deleted_post_ids: set[str],
    posts: Sequence[Post],
    *,
    clues: Sequence[Clue] = (),
    diagnosis_at: datetime | None = None,
) -> list[ProfileCandidateSet]:
    """Re-rank the complete candidate pool after exclusions without rerunning inference."""
    now = diagnosis_at or datetime.now(UTC)
    remaining_by_id = {post.post_id: post for post in posts}
    claims: list[ProfileItem] = []
    for candidate_set in candidate_sets:
        for candidate in candidate_set.candidate_pool:
            candidate_paths = list(candidate.evidence_paths)
            if candidate_set.attribute is ProfileAttribute.REALTIME_LOCATION:
                candidate_paths = [
                    path
                    for path in candidate_paths
                    if (observed_at := _realtime_path_observed_at(path, remaining_by_id))
                    is not None
                    and timedelta(0)
                    <= now.astimezone(UTC) - observed_at.astimezone(UTC)
                    <= timedelta(minutes=15)
                ]
                if not candidate_paths:
                    continue
            item = ProfileItem(
                attribute=candidate_set.attribute,
                value=candidate.value,
                confidence=candidate.confidence,
                status=candidate.status,
                evidence=[reference for path in candidate_paths for reference in path.evidence],
                evidence_paths=candidate_paths,
                assessment=candidate.assessment,
            )
            surviving = recalculate_after_deletion(item, deleted_post_ids)
            if surviving is None:
                continue
            claims.append(surviving)
    surviving_clues = [clue for clue in clues if clue.post_id not in deleted_post_ids]
    return evaluate_profile_candidates(claims, posts, clues=surviving_clues)


def profile_relations_after_deletion(
    relations: Sequence[ProfileRelation],
    deleted_post_ids: Collection[str],
    surviving_claims: Sequence[ProfileCandidateSet],
) -> list[ProfileRelation]:
    """Keep only relation paths and candidate endpoints still supported after deletion."""
    deleted = set(deleted_post_ids)
    claims_by_attribute = {claim.attribute: claim for claim in surviving_claims}
    kept: list[ProfileRelation] = []
    for relation in relations:
        paths = [
            path
            for path in relation.evidence_paths
            if not any(reference.post_id in deleted for reference in path.evidence)
        ]
        endpoints_survive = True
        for endpoint in (relation.left, relation.right):
            if endpoint.kind is not ProfileRelationEndpointKind.PROFILE_CANDIDATE:
                continue
            candidate_set = (
                claims_by_attribute.get(endpoint.attribute) if endpoint.attribute else None
            )
            if candidate_set is None or not any(
                candidate.value == endpoint.value for candidate in candidate_set.candidates
            ):
                endpoints_survive = False
                break
        if paths and endpoints_survive:
            kept.append(relation.model_copy(update={"evidence_paths": paths}))
    return kept


def _minimal_scope(paths: list[ProfileEvidencePath]) -> EvidenceScope:
    return (
        EvidenceScope.BLUESKY
        if any(all(ref.source != "public_web" for ref in path.evidence) for path in paths)
        else EvidenceScope.BLUESKY_PUBLIC_WEB
    )


def infer_web_employer_claim(
    posts: list[Post],
    web_facts: list[WebFact],
    owner_profile_text: str = "",
) -> ProfileItem | None:
    """Infer an employer from explicit naming, another owner post, and a verified legal name.

    The explicit employer anchor identifies the owner relationship; the public source only
    normalizes that named organization to its legal name.
    """
    candidates: dict[str, tuple[str, list[ProfileEvidencePath]]] = {}
    anchors: list[tuple[str | None, str, str]] = [
        (post.post_id, post.text, "post_text") for post in posts
    ]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    eligible_facts = [
        fact
        for fact in web_facts
        # Only normalize the owner-linked organization itself to its legal name.
        # A program, event, campus, tenant, or contractor being associated with a
        # company does not establish that the account owner works there.
        if fact.relation == "legal_name_of"
        and fact.verification_status is WebVerificationStatus.VERIFIED
        and fact.source_kind in {WebSourceKind.OFFICIAL_ORGANIZATION, WebSourceKind.PUBLIC_REGISTRY}
        and _is_organization_name(fact.object)
    ]
    for anchor_post_id, anchor_text, anchor_source in anchors:
        if _forbidden_context(anchor_text):
            continue
        # The Web-backed path requires the post to state that X itself is the
        # employer/name, not merely something belonging to the company.
        for match in re.finditer(
            r"(?:私の勤務先は|私の勤め先は|勤務先は|勤め先は|うちの会社は)(?P<bridge>[^\s、。]+)",
            anchor_text,
        ):
            bridge_text = match.group("bridge").rstrip("ですだにへをがは")
            if not _is_distinctive_bridge(bridge_text):
                continue
            bridge_key = _normalize_bridge(bridge_text)
            for fact in eligible_facts:
                if _normalize_bridge(fact.subject) != bridge_key:
                    continue
                for supporting_post in posts:
                    if (
                        supporting_post.post_id == anchor_post_id
                        or bridge_text not in supporting_post.text
                    ):
                        continue
                    if _forbidden_context(supporting_post.text):
                        continue
                    # Profile anchors still require two independent posts.
                    if anchor_post_id is None:
                        other_posts = [
                            post
                            for post in posts
                            if post.post_id != supporting_post.post_id and bridge_text in post.text
                        ]
                    else:
                        other_posts = [
                            next(post for post in posts if post.post_id == anchor_post_id)
                        ]
                    for other_post in other_posts:
                        evidence = [
                            ProfileEvidence(
                                post_id=anchor_post_id,
                                clue_index=None,
                                required=True,
                                source=anchor_source,
                                excerpt=match.group(0),
                            ),
                            ProfileEvidence(
                                post_id=other_post.post_id
                                if anchor_post_id is None
                                else supporting_post.post_id,
                                clue_index=None,
                                required=True,
                                source="post_text",
                                excerpt=bridge_text,
                            ),
                            ProfileEvidence(
                                source="public_web",
                                web_fact_id=fact.id,
                                required=True,
                            ),
                        ]
                        if anchor_post_id is None:
                            evidence.insert(
                                2,
                                ProfileEvidence(
                                    post_id=supporting_post.post_id,
                                    clue_index=None,
                                    required=True,
                                    source="post_text",
                                    excerpt=bridge_text,
                                ),
                            )
                        key = _normalize_bridge(fact.object)
                        candidates.setdefault(key, (fact.object, []))[1].append(
                            ProfileEvidencePath(
                                evidence=evidence,
                                confidence=0.65,
                                provenance=EvidencePathProvenance.DIRECT_DISCLOSURE,
                            )
                        )
    if len(candidates) != 1:
        return None
    value, paths = next(iter(candidates.values()))
    unique_paths: dict[tuple[tuple[str, str, str], ...], ProfileEvidencePath] = {}
    for path in paths:
        path_key = tuple(
            (ref.source.value, ref.post_id or "", ref.web_fact_id or "") for ref in path.evidence
        )
        unique_paths[path_key] = path
    paths = list(unique_paths.values())
    return ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value=value,
        confidence=0.65,
        status=ProfileStatus.FOUND,
        evidence=[ref for path in paths for ref in path.evidence],
        evidence_paths=paths,
        assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY_PUBLIC_WEB),
    )


def infer_web_employer_claims(
    posts: list[Post], web_facts: list[WebFact], owner_profile_text: str = ""
) -> list[ProfileItem]:
    """Collect separately supported employer candidates from verified legal-name facts."""
    by_value: dict[str, ProfileItem] = {}
    for fact in web_facts:
        claim = infer_web_employer_claim(posts, [fact], owner_profile_text)
        if claim is None or not claim.value:
            continue
        key = _normalize_bridge(claim.value)
        previous = by_value.get(key)
        if previous is None:
            by_value[key] = claim
        else:
            paths = [*previous.evidence_paths, *claim.evidence_paths]
            by_value[key] = previous.model_copy(
                update={
                    "evidence_paths": paths,
                    "evidence": [ref for path in paths for ref in path.evidence],
                }
            )
    return list(by_value.values())


_RULE_CONCLUSION_MAPPING: dict[tuple[str, str], tuple[ProfileAttribute, float]] = {
    ("R1", "home_area"): (ProfileAttribute.RESIDENTIAL_AREA, 0.60),
    ("R1", "station"): (ProfileAttribute.HOME_NEAREST_STATION, 0.58),
    ("R2", "active_time"): (ProfileAttribute.ACTIVE_TIME, 0.58),
    ("R3", "routine"): (ProfileAttribute.ROUTINE, 0.58),
    ("R4", "home_city"): (ProfileAttribute.RESIDENTIAL_AREA, 0.56),
    ("R5", "home_district"): (ProfileAttribute.RESIDENTIAL_AREA, 0.58),
    ("R6", "home_block"): (ProfileAttribute.RESIDENTIAL_AREA, 0.62),
    ("R7", "school"): (ProfileAttribute.SCHOOL, 0.58),
    ("R8", "full_name"): (ProfileAttribute.FULL_NAME, 0.60),
    ("R8", "given_name_or_nickname"): (ProfileAttribute.GIVEN_NAME, 0.60),
    ("R9", "age"): (ProfileAttribute.AGE, 0.58),
    ("R10", "occupation"): (ProfileAttribute.OCCUPATION, 0.58),
    ("R11", "line"): (ProfileAttribute.REGULAR_LINE, 0.56),
    ("R12", "birthday"): (ProfileAttribute.BIRTHDAY, 0.58),
    ("X2", "birthday"): (ProfileAttribute.BIRTHDAY, 0.62),
    ("X3", "long_term_home_absence"): (ProfileAttribute.ANNOUNCED_LONG_ABSENCE, 0.58),
    ("X4", "frequent_shop"): (ProfileAttribute.FREQUENT_SHOP, 0.56),
    ("X5", "workplace"): (ProfileAttribute.EMPLOYER_NAME, 0.56),
}


def _build_conclusion_evidence(
    conclusion: Conclusion,
    posts: Sequence[Post],
    clues: Sequence[Clue],
) -> list[ProfileEvidence]:
    """Convert a RulesR/RulesX conclusion into >= 2 grounded ProfileEvidence entries."""
    posts_by_id = {post.post_id: post for post in posts}
    valid_indices = list(dict.fromkeys(i for i in conclusion.clue_indices if 0 <= i < len(clues)))
    evidence: list[ProfileEvidence] = [
        ProfileEvidence(
            post_id=clues[i].post_id,
            clue_index=i,
            required=True,
            source=EvidenceSource.CLUE,
        )
        for i in valid_indices
    ]
    if len(evidence) == 1:
        clue = clues[valid_indices[0]]
        post = posts_by_id.get(clue.post_id)
        excerpt = (
            (post.text.strip() if post is not None else "")
            or clue.value.strip()
            or conclusion.note.strip()
            or conclusion.value.strip()
        )[:200]
        if excerpt:
            evidence.append(
                ProfileEvidence(
                    post_id=clue.post_id,
                    clue_index=None,
                    required=True,
                    source=EvidenceSource.POST_TEXT,
                    excerpt=excerpt,
                )
            )
    elif len(evidence) == 0:
        weekday_match = re.search(rf"毎週([{WEEKDAYS}])曜", conclusion.value)
        matching_posts: list[Post] = []
        if weekday_match is not None:
            target_day = WEEKDAYS.index(weekday_match.group(1))
            jst = timezone(timedelta(hours=9))
            matching_posts = [
                post for post in posts if post.created_at.astimezone(jst).weekday() == target_day
            ]
        if len(matching_posts) < 2 and timestamps_usable(posts):
            matching_posts = list(posts)[:5]
        seen_post_ids: set[str] = set()
        for post in matching_posts:
            if post.post_id in seen_post_ids:
                continue
            seen_post_ids.add(post.post_id)
            evidence.append(
                ProfileEvidence(
                    post_id=post.post_id,
                    clue_index=None,
                    required=True,
                    source=EvidenceSource.POST_TEXT,
                    excerpt=(post.text.strip() or post.created_at.isoformat())[:200],
                )
            )
            if len(evidence) >= 5:
                break
    return evidence if len(evidence) >= 2 else []


def infer_rule_and_link_claims(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    gazetteer: Gazetteer | None = None,
) -> list[ProfileItem]:
    """Convert RulesR (R1..R12) and RulesX (X2..X5) conclusions into ProfileItem candidates."""
    conclusions = infer(list(clues), list(posts), gazetteer or Gazetteer())
    grouped_paths: dict[tuple[ProfileAttribute, str], list[ProfileEvidencePath]] = {}
    for conclusion in conclusions:
        mapped = _RULE_CONCLUSION_MAPPING.get((conclusion.rule, conclusion.attribute))
        if mapped is None:
            continue
        attribute, cap = mapped
        value = conclusion.value.strip()
        if not value:
            continue
        evidence = _build_conclusion_evidence(conclusion, posts, clues)
        if len(evidence) < 2:
            continue
        path_confidence = round(max(0.55, min(cap, conclusion.confidence)), 2)
        grouped_paths.setdefault((attribute, value), []).append(
            ProfileEvidencePath(
                evidence=evidence,
                confidence=path_confidence,
                provenance=EvidencePathProvenance.COMBINED_INFERENCE,
            )
        )
    items: list[ProfileItem] = []
    for (attribute, value), paths in grouped_paths.items():
        items.append(
            ProfileItem(
                attribute=attribute,
                value=value,
                confidence=max(path.confidence for path in paths),
                status=ProfileStatus.WEAK,
                evidence=[ref for path in paths for ref in path.evidence],
                evidence_paths=paths,
                assessment=ClaimAssessment(minimal_scope=_minimal_scope(paths)),
            )
        )
    return items


def infer_owner_claims_with_web(
    posts: list[Post],
    clues: list[Clue],
    web_facts: list[WebFact],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
    gazetteer: Gazetteer | None = None,
    *,
    diagnosis_date: date | None = None,
    diagnosis_at: datetime | None = None,
    include_heuristic_rules: bool = False,
    photo_place_results: Sequence[PhotoPlaceResult] = (),
) -> list[ProfileItem]:
    """Combine direct and Web-backed paths; reject conflicting employer names."""
    claims = infer_owner_claims(
        posts,
        clues,
        owner_profile_text,
        self_report_clues,
        gazetteer,
        diagnosis_date=diagnosis_date,
        diagnosis_at=diagnosis_at,
        include_heuristic_rules=include_heuristic_rules,
        photo_place_results=photo_place_results,
    )
    registry_claim = (
        infer_registry_employer_claim(posts, owner_profile_text, gazetteer)
        if gazetteer is not None
        else None
    )
    # The offline registry is authoritative for names it can verify; use WebFacts only
    # when the local registry has no unique employer match.
    web_claims = (
        [registry_claim]
        if registry_claim is not None
        else infer_web_employer_claims(posts, web_facts, owner_profile_text)
    )
    if not web_claims:
        return claims
    direct_by_value = {
        _normalize_bridge(item.value or ""): item
        for item in claims
        if item.attribute is ProfileAttribute.EMPLOYER_NAME and item.value
    }
    employer_results = list(direct_by_value.values())
    for web_claim in web_claims:
        key = _normalize_bridge(web_claim.value or "")
        direct = direct_by_value.get(key)
        if direct is None:
            employer_results.append(web_claim)
            continue
        paths = [*direct.evidence_paths, *web_claim.evidence_paths]
        merged = direct.model_copy(
            update={
                "evidence_paths": paths,
                "evidence": [ref for path in paths for ref in path.evidence],
                "assessment": direct.assessment.model_copy(
                    update={"minimal_scope": _minimal_scope(paths)}
                ),
            }
        )
        employer_results = [item for item in employer_results if item is not direct]
        employer_results.append(merged)
    return [
        item for item in claims if item.attribute is not ProfileAttribute.EMPLOYER_NAME
    ] + employer_results


def infer_owner_candidate_sets_with_web(
    posts: list[Post],
    clues: list[Clue],
    web_facts: list[WebFact],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
    gazetteer: Gazetteer | None = None,
    *,
    diagnosis_date: date | None = None,
    diagnosis_at: datetime | None = None,
    include_heuristic_rules: bool = True,
    photo_place_results: Sequence[PhotoPlaceResult] = (),
) -> list[ProfileCandidateSet]:
    """Public multi-candidate entry point; returns one set for each supported catalog item."""
    claims = infer_owner_claims_with_web(
        posts,
        clues,
        web_facts,
        owner_profile_text,
        self_report_clues,
        gazetteer,
        diagnosis_date=diagnosis_date,
        diagnosis_at=diagnosis_at,
        include_heuristic_rules=include_heuristic_rules,
        photo_place_results=photo_place_results,
    )
    return evaluate_profile_candidates(claims, posts, clues=clues)


_COMMUTE_DESTINATION_RE = re.compile(
    r"(?:私|自分)(?:は|が)[^。！？\n]{0,20}(?:通勤先|勤務先)(?:は|が)(?P<value>[^、。\s]+)"
)
_SCHOOL_DESTINATION_RE = re.compile(
    r"(?:私|自分)(?:は|が)[^。！？\n]{0,20}通学先(?:は|が)(?P<value>[^、。\s]+)"
)


def infer_owner_profile_relations(
    posts: Sequence[Post],
    profile_claims: Sequence[ProfileCandidateSet],
    *,
    clues: Sequence[Clue] = (),
    gazetteer: Gazetteer | None = None,
) -> list[ProfileRelation]:
    """Create scoreless links from explicit owner wording, independent paths, and RulesX X1."""
    by_attribute = {claim.attribute: claim for claim in profile_claims}
    relations: list[ProfileRelation] = []
    posts_by_id = {post.post_id: post for post in posts}
    home = by_attribute.get(ProfileAttribute.HOME_NEAREST_STATION)
    regular = by_attribute.get(ProfileAttribute.REGULAR_STATION)
    if home and regular:
        for home_candidate in home.candidates:
            for regular_candidate in regular.candidates:
                if (
                    unicodedata.normalize("NFKC", home_candidate.value).strip()
                    != unicodedata.normalize("NFKC", regular_candidate.value).strip()
                ):
                    continue
                for home_path in home_candidate.evidence_paths:
                    if not any(
                        ref.source.value == "post_text"
                        and HOME_ORIGIN_CLAIM_RE.search(ref.excerpt or "")
                        and ref.post_id in posts_by_id
                        and HOME_ORIGIN_TEXT_RE.search(
                            unicodedata.normalize("NFKC", posts_by_id[ref.post_id].text)
                        )
                        for ref in home_path.evidence
                    ):
                        continue
                    for regular_path in regular_candidate.evidence_paths:
                        if not any(
                            ref.source.value == "post_text"
                            and HOME_ORIGIN_ROUTINE_RE.search(ref.excerpt or "")
                            for ref in regular_path.evidence
                        ):
                            continue
                        refs = _unique_relation_evidence(
                            [*home_path.evidence, *regular_path.evidence]
                        )
                        if len({ref.post_id for ref in refs if ref.post_id}) < 2:
                            continue
                        relations.append(
                            ProfileRelation(
                                kind=ProfileRelationKind.HOME_NEAREST_IS_COMMUTE_ORIGIN,
                                left=ProfileRelationEndpoint(
                                    kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
                                    attribute=ProfileAttribute.HOME_NEAREST_STATION,
                                    value=home_candidate.value,
                                ),
                                right=ProfileRelationEndpoint(
                                    kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
                                    attribute=ProfileAttribute.REGULAR_STATION,
                                    value=regular_candidate.value,
                                ),
                                evidence_paths=[
                                    ProfileEvidencePath(
                                        evidence=refs,
                                        confidence=min(
                                            home_path.confidence, regular_path.confidence
                                        ),
                                        provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                                    )
                                ],
                            )
                        )

    for post in posts:
        destination_matches = (
            (
                _COMMUTE_DESTINATION_RE.search(post.text),
                ProfileAttribute.EMPLOYER_NAME,
                ProfileRelationKind.COMMUTE_DESTINATION_IS_EMPLOYER,
            ),
            (
                _SCHOOL_DESTINATION_RE.search(post.text),
                ProfileAttribute.SCHOOL,
                ProfileRelationKind.COMMUTE_DESTINATION_IS_SCHOOL,
            ),
        )
        for match, attribute, kind in destination_matches:
            if (
                not match
                or _forbidden_context(post.text)
                or _has_quoted_or_fiction_context(post.text)
                or _third_party_context(post.text, attribute, match.start("value"))
                or _is_negated_claim(post.text, match.end("value"))
            ):
                continue
            value = re.sub(r"(?:です|だ)$", "", match.group("value")).strip()
            candidate_set = by_attribute.get(attribute)
            if candidate_set is None:
                continue
            for candidate in candidate_set.candidates:
                if (
                    unicodedata.normalize("NFKC", candidate.value).strip()
                    != unicodedata.normalize("NFKC", value).strip()
                ):
                    continue
                relation_ref = ProfileEvidence(
                    post_id=post.post_id,
                    clue_index=None,
                    required=True,
                    source="post_text",
                    excerpt=match.group(0),
                )
                for candidate_path in candidate.evidence_paths:
                    # Destination wording cannot be the independent observation of the affiliation.
                    if any(
                        ref.post_id == post.post_id for ref in candidate_path.evidence
                    ) or not any(
                        ref.source.value == "clue"
                        and ref.post_id is not None
                        and ref.post_id != post.post_id
                        for ref in candidate_path.evidence
                    ):
                        continue
                    refs = _unique_relation_evidence([relation_ref, *candidate_path.evidence])
                    if len({ref.post_id for ref in refs if ref.post_id}) < 2:
                        continue
                    candidate_endpoint = ProfileRelationEndpoint(
                        kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
                        attribute=attribute,
                        value=candidate.value,
                    )
                    destination_endpoint = ProfileRelationEndpoint(
                        kind=ProfileRelationEndpointKind.COMMUTE_DESTINATION, value=value
                    )
                    relations.append(
                        ProfileRelation(
                            kind=kind,
                            left=destination_endpoint,
                            right=candidate_endpoint,
                            evidence_paths=[
                                ProfileEvidencePath(
                                    evidence=refs,
                                    confidence=min(0.55, candidate_path.confidence),
                                    provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                                )
                            ],
                        )
                    )
    if clues:
        rule_conclusions = infer(list(clues), list(posts), gazetteer or Gazetteer())
        school_set = by_attribute.get(ProfileAttribute.SCHOOL)
        if school_set is not None and school_set.candidates:
            candidate_by_norm = {
                unicodedata.normalize("NFKC", candidate.value).strip(): candidate
                for candidate in school_set.candidates
            }
            for conclusion in rule_conclusions:
                if conclusion.rule != "X1" or conclusion.attribute != "home_school_commute":
                    continue
                x1_match = re.fullmatch(
                    r".+?付近から(.+)へ通学している可能性", conclusion.value.strip()
                )
                if x1_match is None:
                    continue
                school_norm = unicodedata.normalize("NFKC", x1_match.group(1)).strip()
                matched_candidate = candidate_by_norm.get(school_norm)
                if matched_candidate is None:
                    continue
                evidence = _build_conclusion_evidence(conclusion, posts, clues)
                if len(evidence) < 2:
                    continue
                relations.append(
                    ProfileRelation(
                        kind=ProfileRelationKind.COMMUTE_DESTINATION_IS_SCHOOL,
                        left=ProfileRelationEndpoint(
                            kind=ProfileRelationEndpointKind.COMMUTE_DESTINATION,
                            value=matched_candidate.value,
                        ),
                        right=ProfileRelationEndpoint(
                            kind=ProfileRelationEndpointKind.PROFILE_CANDIDATE,
                            attribute=ProfileAttribute.SCHOOL,
                            value=matched_candidate.value,
                        ),
                        evidence_paths=[
                            ProfileEvidencePath(
                                evidence=evidence,
                                confidence=round(max(0.55, min(0.60, conclusion.confidence)), 2),
                                provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                            )
                        ],
                    )
                )
    grouped: dict[tuple[str, str, str, str], list[ProfileEvidencePath]] = {}
    endpoints_by_key: dict[
        tuple[str, str, str, str],
        tuple[ProfileRelationKind, ProfileRelationEndpoint, ProfileRelationEndpoint],
    ] = {}
    for relation in relations:
        key = (
            relation.kind.value,
            relation.left.kind.value,
            relation.left.attribute.value if relation.left.attribute else "",
            relation.left.value
            + "\0"
            + relation.right.kind.value
            + "\0"
            + (relation.right.attribute.value if relation.right.attribute else "")
            + "\0"
            + relation.right.value,
        )
        grouped.setdefault(key, []).extend(relation.evidence_paths)
        endpoints_by_key.setdefault(key, (relation.kind, relation.left, relation.right))
    result: list[ProfileRelation] = []
    for key, paths in grouped.items():
        unique_paths: dict[str, ProfileEvidencePath] = {}
        for path in paths:
            path_key = path.model_dump_json(exclude_none=True)
            unique_paths.setdefault(path_key, path)
        kind, left, right = endpoints_by_key[key]
        result.append(
            ProfileRelation(
                kind=kind, left=left, right=right, evidence_paths=list(unique_paths.values())
            )
        )
    return result


def _unique_relation_evidence(evidence: Sequence[ProfileEvidence]) -> list[ProfileEvidence]:
    unique: dict[tuple[object, ...], ProfileEvidence] = {}
    for reference in evidence:
        key = (
            reference.source.value,
            reference.post_id,
            reference.clue_index,
            reference.image_index,
            reference.web_fact_id,
            reference.excerpt,
        )
        unique.setdefault(key, reference)
    return list(unique.values())


def infer_owner_claims(
    posts: list[Post],
    clues: list[Clue],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
    gazetteer: Gazetteer | None = None,
    *,
    diagnosis_date: date | None = None,
    diagnosis_at: datetime | None = None,
    include_heuristic_rules: bool = False,
    photo_place_results: Sequence[PhotoPlaceResult] = (),
) -> list[ProfileItem]:
    """Infer only limited claims with explicit owner/context evidence.

    Residential pattern: an owner post names ``自宅近くのX`` and a different post says
    ``XはY``. Regular-station claims require an explicit commute-habit post and a separate
    post tying an OCR station sign to the owner's usual commute station. Employer inference
    from possessive phrases is intentionally disabled.
    """
    facts: list[CrossPostFact] = []
    self_report_clues = self_report_clues or []
    confidence = 0.65  # conservative provisional rule confidence; never presented as calibrated
    anchors: list[tuple[str | None, str, str]] = [
        (post.post_id, post.text, "post_text") for post in posts
    ]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    for anchor_post_id, anchor_text, anchor_source in anchors:
        if _forbidden_context(anchor_text):
            continue
        for _attribute, anchor_pattern, value_pattern, clue_type, validator in (
            (
                ProfileAttribute.RESIDENTIAL_AREA,
                r"自宅近くの(?P<bridge>[^\s、。]+)",
                r"{bridge}(?:は|が)(?P<value>[^\s、。]+)",
                ClueType.PLACE_TEXT,
                _is_residential_value,
            ),
        ):
            anchor_match = re.search(anchor_pattern, anchor_text)
            if not anchor_match:
                continue
            bridge_text = anchor_match.group("bridge").rstrip("ですだにへをがは")
            bridge = _normalize_bridge(bridge_text)
            if not _is_distinctive_bridge(bridge_text):
                continue
            bridge_id = f"home:{bridge}"
            facts.append(
                CrossPostFact(
                    anchor_post_id,
                    None,
                    FactRole.OWNER_RELATION,
                    bridge_text,
                    confidence,
                    bridge_id,
                    True,
                    excerpt=anchor_match.group(0),
                    source=anchor_source,
                )
            )

            for supporting_post in posts:
                if _forbidden_context(supporting_post.text):
                    continue
                if (
                    supporting_post.post_id != anchor_post_id
                    and bridge_text in supporting_post.text
                ):
                    facts.append(
                        CrossPostFact(
                            supporting_post.post_id,
                            None,
                            FactRole.BRIDGE,
                            bridge_text,
                            confidence,
                            bridge_id,
                            excerpt=bridge_text,
                        )
                    )
                if supporting_post.post_id == anchor_post_id:
                    continue
                match = re.search(
                    value_pattern.format(bridge=re.escape(bridge_text)), supporting_post.text
                )
                if not match:
                    continue
                value = match.group("value").rstrip("ですだにへをがは")
                if not value or not validator(value):
                    continue
                typed = _matching_text_clue(clues, supporting_post.post_id, value, clue_type)
                if typed is None:
                    continue
                clue_index, clue = typed
                facts.append(
                    CrossPostFact(
                        supporting_post.post_id,
                        clue_index,
                        FactRole.SPECIFIC_VALUE,
                        value,
                        clue.confidence,
                        bridge_id,
                        excerpt=match.group(0),
                        related_evidence=(
                            ProfileEvidence(
                                post_id=supporting_post.post_id,
                                clue_index=None,
                                required=True,
                                source="post_text",
                                excerpt=match.group(0),
                            ),
                        ),
                    )
                )

            if owner_profile_text.strip():
                match = re.search(
                    value_pattern.format(bridge=re.escape(bridge_text)), owner_profile_text
                )
                if match:
                    value = match.group("value").rstrip("ですだにへをがは")
                    profile_clue = _matching_profile_clue(self_report_clues, value, clue_type)
                    if value and validator(value) and profile_clue:
                        facts.append(
                            CrossPostFact(
                                None,
                                None,
                                FactRole.SPECIFIC_VALUE,
                                value,
                                profile_clue.confidence,
                                bridge_id,
                                excerpt=match.group(0),
                                source="profile_text",
                            )
                        )

    # A photo may contribute a coarse area only when the same post explicitly places
    # the owner's home nearby, and a separate post independently anchors that area.
    facts.extend(_photo_home_area_facts(posts, clues, photo_place_results))

    if gazetteer is not None:
        facts.extend(shelter_home_facts(posts, clues, owner_profile_text, gazetteer))
        facts.extend(bus_stop_home_facts(posts, clues, owner_profile_text, gazetteer))
    claims = infer_cross_post_candidates(ProfileAttribute.RESIDENTIAL_AREA, facts)
    claims.extend(infer_workplace_area_claims(posts, clues))
    claims.extend(infer_child_age_claims(posts, diagnosis_date=diagnosis_date))
    claims.extend(infer_school_claims(posts, clues))
    if gazetteer is not None:
        claims.extend(infer_regular_station_claims(posts, clues, gazetteer))
        claims.extend(
            infer_regular_station_from_home_origin(
                posts, clues, gazetteer, diagnosis_at=diagnosis_at
            )
        )
        claims.extend(infer_combined_regular_line_claims(posts, clues, gazetteer))
        claims.extend(infer_home_nearest_station_claims(posts, clues, gazetteer))
    claims.extend(infer_realtime_location_claims(posts, clues, diagnosis_at=diagnosis_at))
    claims.extend(infer_explicit_observation_claims(posts, clues, diagnosis_at=diagnosis_at))
    claims.extend(infer_frequent_shop_claims(posts, clues))
    if gazetteer is not None:
        claims.extend(infer_child_school_claims(posts, clues, gazetteer))
        claims = add_school_district_residence(claims, gazetteer)
    if include_heuristic_rules:
        claims.extend(infer_rule_and_link_claims(posts, clues, gazetteer))
    return claims


_PHOTO_HOME_PREFIX = re.compile(
    r"(?:\u81ea\u5b85|\u5bb6|\u3046\u3061|\u81ea\u5206\u306e\u5bb6)(?:\u306e)?"
    r"(?:\u8fd1\u304f|\u8fd1\u6240|\u305d\u3070)(?:\u306b\u3042\u308b|\u306e|\u306b|\u3067)?\s*"
)


def _photo_home_place_match(text: str, label: str) -> re.Match[str] | None:
    if not label.strip():
        return None
    pattern = re.compile(rf"{_PHOTO_HOME_PREFIX.pattern}{re.escape(label.strip())}")
    return pattern.search(text)


_PHOTO_AREA_OWNER_CONTEXT_RE = re.compile(
    r"(?:\u8fd1\u6240|\u5730\u5143|\u5e30\u5b85|\u5e30\u308a|\u6700\u5bc4\u308a|"
    r"\u901a\u52e4|\u6bce\u65e5|\u666e\u6bb5|\u4f4f\u3093)"
)
_PHOTO_AREA_EXCLUDED_RE = re.compile(
    r"\u65c5\u884c|\u89b3\u5149|\u51fa\u5f35|\u8a2a\u554f|\u898b\u5b66|"
    r"\u904a\u3073\u306b|\u4e00\u6642\u7684|\u5f15\u7528|\u30ea\u30dd\u30b9\u30c8|RT"
)


def _photo_home_area_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    results: Sequence[PhotoPlaceResult],
) -> list[CrossPostFact]:
    posts_by_id = {post.post_id: post for post in posts}
    facts: list[CrossPostFact] = []
    for result in results:
        photo_post = posts_by_id.get(result.post_id)
        if (
            photo_post is None
            or result.status is not PhotoPlaceStatus.CANDIDATE
            or result.granularity is not PhotoPlaceGranularity.FACILITY
            or result.lookup_status
            not in {
                PhotoPlaceLookupStatus.LOCAL_ONLY,
                PhotoPlaceLookupStatus.REFERENCE_CHECKED,
                PhotoPlaceLookupStatus.UNAVAILABLE,
                PhotoPlaceLookupStatus.WEB_SEARCHED,
            }
            or _forbidden_context(photo_post.text)
            or _has_quoted_or_fiction_context(photo_post.text)
            or _PHOTO_AREA_EXCLUDED_RE.search(photo_post.text)
        ):
            continue
        candidate = result.candidates[0]
        if (
            candidate.place_type not in {PhotoPlaceType.FACILITY, PhotoPlaceType.LANDMARK}
            or candidate.photo_relation is not PhotoPlaceRelation.VISIBLE_IN_FRAME
        ):
            continue
        # Brave結果は検証済みの事実ではない。ちょうど1件のBrave由来候補（ローカル候補と
        # 混ざらない）で、市区町村が分かる場合に限り、弱い根拠として扱う。
        if result.lookup_status is PhotoPlaceLookupStatus.WEB_SEARCHED and (
            len(result.candidates) != 1
            or not candidate.place_id.startswith("brave-place:")
            or any(source.provider != "Brave Search Place Search" for source in candidate.sources)
        ):
            continue
        home_match = _photo_home_place_match(photo_post.text, candidate.label)
        if home_match is None or _is_negated_claim(photo_post.text, home_match.end()):
            continue
        area = (candidate.area_label or "").strip()
        if (
            not area
            or not candidate.sources
            or any(not source.license_id for source in candidate.sources)
        ):
            continue
        image_refs: list[ProfileEvidence] = []
        candidate_name_keys = set(place_name_keys(candidate.label))
        for evidence in candidate.evidence:
            if evidence.clue_index is None or evidence.clue_index >= len(clues):
                continue
            clue = clues[evidence.clue_index]
            if clue.post_id != result.post_id or clue.image_index != result.image_index:
                continue
            if not candidate_name_keys.intersection(place_name_keys(clue.value)):
                continue
            image_refs.append(
                ProfileEvidence(
                    post_id=result.post_id,
                    clue_index=evidence.clue_index,
                    required=True,
                    source=EvidenceSource.CLUE,
                )
            )
        if not image_refs:
            continue
        bridge_id = f"home:photo:{_normalize_bridge(candidate.place_id)}"
        facts.append(
            CrossPostFact(
                result.post_id,
                None,
                FactRole.OWNER_RELATION,
                candidate.label,
                0.65,
                bridge_id,
                True,
                context=photo_post.text,
                excerpt=home_match.group(0),
                related_evidence=(
                    ProfileEvidence(
                        post_id=result.post_id,
                        clue_index=None,
                        required=True,
                        source=EvidenceSource.POST_TEXT,
                        excerpt=home_match.group(0),
                    ),
                    *image_refs,
                ),
            )
        )

        for supporting_post in posts:
            if (
                supporting_post.post_id == result.post_id
                or _forbidden_context(supporting_post.text)
                or _has_quoted_or_fiction_context(supporting_post.text)
                or _PHOTO_AREA_EXCLUDED_RE.search(supporting_post.text)
            ):
                continue
            area_match = re.search(re.escape(area), supporting_post.text, re.IGNORECASE)
            if not area_match or not _photo_area_has_owner_context(
                supporting_post.text, area_match
            ):
                continue
            if _is_negated_claim(supporting_post.text, area_match.end()):
                continue
            typed = _matching_text_clue(clues, supporting_post.post_id, area, ClueType.PLACE_TEXT)
            if typed is None:
                continue
            clue_index, clue = typed
            facts.append(
                CrossPostFact(
                    supporting_post.post_id,
                    clue_index,
                    FactRole.SPECIFIC_VALUE,
                    area,
                    min(0.65, clue.confidence),
                    bridge_id,
                    context=supporting_post.text,
                    excerpt=area_match.group(0),
                    related_evidence=(
                        ProfileEvidence(
                            post_id=supporting_post.post_id,
                            clue_index=None,
                            required=True,
                            source=EvidenceSource.POST_TEXT,
                            excerpt=area_match.group(0),
                        ),
                    ),
                )
            )
    return facts


def _photo_area_has_owner_context(text: str, area_match: re.Match[str]) -> bool:
    start = max(0, area_match.start() - 24)
    end = min(len(text), area_match.end() + 24)
    local_context = text[start:end]
    return bool(_PHOTO_AREA_OWNER_CONTEXT_RE.search(local_context))


HOME_ORIGIN_TEXT_RE = re.compile(
    r"(?:私|自分|僕|俺)(?:の|は|が)(?:自宅|家)(?:の)?最寄り(?:駅)?は(?P<station>[^、。\s]+?駅)(?:です|だ|$)"
)
HOME_ORIGIN_CLAIM_RE = re.compile(
    r"(?:自宅|家)(?:の)?最寄り(?:駅)?は(?P<station>[^、。\s]+?駅)(?:です|だ|$)"
)
HOME_ORIGIN_ROUTINE_RE = re.compile(
    r"(?:私|自分|僕|俺)(?:は|が)[^。！？\n]{0,35}(?:毎朝|毎日|平日は|普段)[^。！？\n]{0,35}(?:自宅|家)(?:の)?最寄り(?:駅)?から通勤"
)
THIRD_PARTY_HOME_CONTEXT_RE = re.compile(
    r"(?:友人|友達|知人|同僚|他人|家族|彼女?|母|父|兄|姉|妹|弟)[^。！？\n]{0,30}(?:自宅|家)(?:の)?最寄り"
)
MOVE_CONTEXT_RE = re.compile(r"(?:引っ越|転居|転校|転職|異動|住み替え|最寄りが変わ|引越)")


def infer_regular_station_from_home_origin(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    gazetteer: Gazetteer,
    *,
    diagnosis_at: datetime | None = None,
) -> list[ProfileItem]:
    """Add a weak regular-station path from separate dated home and commute posts."""
    known: set[str] = set()
    for row in gazetteer.stations:
        station_name = row.get("station_name")
        if isinstance(station_name, str) and station_name.strip():
            known.add(unicodedata.normalize("NFKC", station_name).strip())
    eligible: list[tuple[Post, str, list[ProfileEvidence]]] = []
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        match = HOME_ORIGIN_TEXT_RE.search(text)
        if (
            not match
            or _forbidden_context(text)
            or _has_quoted_or_fiction_context(text)
            or _third_party_context(text, ProfileAttribute.HOME_NEAREST_STATION, match.start())
            or MOVE_CONTEXT_RE.search(text)
        ):
            continue
        station = unicodedata.normalize("NFKC", match.group("station")).removesuffix("駅").strip()
        if station not in known or _is_negated_claim(text, match.end("station")):
            continue
        station_signs = [
            clue
            for clue in clues
            if clue.post_id == post.post_id and clue.type is ClueType.STATION_SIGN
        ]
        if any("x" in unicodedata.normalize("NFKC", clue.value).lower() for clue in station_signs):
            continue
        observed_station_values = {
            unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip()
            for clue in clues
            if clue.post_id == post.post_id
            and clue.type in {ClueType.PLACE_TEXT, ClueType.STATION_SIGN}
            and unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip() in known
        }
        if observed_station_values and observed_station_values != {station}:
            continue
        typed = [
            (index, clue)
            for index, clue in enumerate(clues)
            if clue.post_id == post.post_id
            and clue.type in {ClueType.PLACE_TEXT, ClueType.STATION_SIGN}
            and clue.source in {ClueSource.TEXT, ClueSource.OCR, ClueSource.VLM}
            and unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip() == station
            and clue.confidence >= 0.5
        ]
        if not typed:
            continue
        evidence = [
            ProfileEvidence(
                post_id=post.post_id,
                clue_index=None,
                required=True,
                source="post_text",
                excerpt=match.group(0),
            )
        ]
        evidence.extend(
            ProfileEvidence(post_id=post.post_id, clue_index=index, required=True)
            for index, _ in typed
        )
        eligible.append((post, station, evidence))

    routines: list[tuple[Post, str, list[ProfileEvidence]]] = []
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        match = HOME_ORIGIN_ROUTINE_RE.search(text)
        if (
            not match
            or _forbidden_context(text)
            or _has_quoted_or_fiction_context(text)
            or _third_party_context(text, ProfileAttribute.REGULAR_STATION, match.start())
            or THIRD_PARTY_HOME_CONTEXT_RE.search(text)
            or MOVE_CONTEXT_RE.search(text)
            or _is_negated_claim(text, match.end())
        ):
            continue
        typed = [
            (index, clue)
            for index, clue in enumerate(clues)
            if clue.post_id == post.post_id
            and clue.type is ClueType.ROUTINE_TEXT
            and clue.source is ClueSource.TEXT
            and clue.value.strip() in text
            and HOME_ORIGIN_ROUTINE_RE.search(unicodedata.normalize("NFKC", clue.value))
        ]
        if not typed:
            continue
        evidence = [
            ProfileEvidence(
                post_id=post.post_id,
                clue_index=None,
                required=True,
                source="post_text",
                excerpt=match.group(0),
            )
        ]
        evidence.extend(
            ProfileEvidence(post_id=post.post_id, clue_index=index, required=True)
            for index, _ in typed
        )
        routines.append((post, match.group(0), evidence))

    claims: list[ProfileItem] = []
    max_gap = timedelta(days=90)
    now = diagnosis_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        return []
    for origin, station, origin_refs in eligible:
        for routine_post, _routine_excerpt, routine_refs in routines:
            if origin.post_id == routine_post.post_id:
                continue
            if origin.created_at is None or routine_post.created_at is None:
                continue
            origin_at, routine_at = origin.created_at, routine_post.created_at
            if (
                origin_at.tzinfo is None
                or routine_at.tzinfo is None
                or origin_at.utcoffset() is None
                or routine_at.utcoffset() is None
            ):
                continue
            start, end = sorted((origin_at, routine_at))
            if end - start > max_gap or end.astimezone(UTC) > now.astimezone(UTC):
                continue
            invalid_or_moving_context = False
            for post in posts:
                if not MOVE_CONTEXT_RE.search(post.text):
                    continue
                if (
                    post.created_at is None
                    or post.created_at.tzinfo is None
                    or post.created_at.utcoffset() is None
                ):
                    invalid_or_moving_context = True
                    break
                if start < post.created_at < end:
                    invalid_or_moving_context = True
                    break
            if invalid_or_moving_context:
                continue
            evidence = _unique_relation_evidence([*origin_refs, *routine_refs])
            # One evidence path is a conjunction of two independent dated owner posts.
            if len({ref.post_id for ref in evidence if ref.post_id}) != 2:
                continue
            path = ProfileEvidencePath(
                evidence=evidence,
                confidence=0.55,
                provenance=EvidencePathProvenance.COMBINED_INFERENCE,
            )
            claims.append(
                ProfileItem(
                    attribute=ProfileAttribute.REGULAR_STATION,
                    value=f"{station}駅",
                    confidence=0.55,
                    status=ProfileStatus.WEAK,
                    evidence=evidence,
                    evidence_paths=[path],
                    assessment=ClaimAssessment(
                        minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                    ),
                )
            )
    return claims


_COMMUTE_ROUTINE_RE = re.compile(r"(?:毎朝|毎日|平日は|週[一二三四五六日1-7]回|いつも|普段)")


def infer_combined_regular_line_claims(
    posts: Sequence[Post], clues: Sequence[Clue], gazetteer: Gazetteer
) -> list[ProfileItem]:
    """Infer a listed line from repeated, owner-stated commute endpoints.

    The result is only a candidate line shared by both station records, not proof of
    the person's actual route. Exact typed observations are required in every post.
    """
    rows = getattr(gazetteer, "stations", None)
    if not isinstance(rows, list) or not rows:
        return []
    station_records: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            return []
        station = row.get("station_name")
        operator = row.get("operator")
        line = row.get("line_name")
        if not (
            isinstance(station, str)
            and station.strip()
            and isinstance(operator, str)
            and operator.strip()
            and isinstance(line, str)
            and line.strip()
        ):
            return []
        station_records.setdefault(unicodedata.normalize("NFKC", station).strip(), set()).add(
            (
                unicodedata.normalize("NFKC", operator).strip(),
                unicodedata.normalize("NFKC", line).strip(),
            )
        )
    station_pattern = "|".join(
        re.escape(name) for name in sorted(station_records, key=len, reverse=True)
    )
    if not station_pattern:
        return []
    commute_endpoints_re = re.compile(
        r"(?P<owner>(?:私|自分|僕|俺)(?:は|が))[^。！？\n]{0,60}?"
        rf"(?P<origin>{station_pattern})駅から(?P<destination>{station_pattern})駅まで"
        r"[^。！？\n]{0,24}?"
        r"(?:通勤(?:している|しています|していた|していました|する|します)|"
        r"通って(?:いる|います|いた|いました))(?=$|[。！？\n])"
    )

    candidates: dict[tuple[str, str, str, str], list[tuple[Post, re.Match[str], int, int]]] = {}
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        if (
            _forbidden_context(text)
            or _has_quoted_or_fiction_context(text)
            or any(word in text for word in ("イベント", "ライブ", "観光", "旅行", "出張", "参加"))
        ):
            continue
        for match in commute_endpoints_re.finditer(text):
            sentence_start = max(text.rfind(mark, 0, match.start()) for mark in "。！？\n") + 1
            sentence_end = min(
                (pos for mark in "。！？\n" if (pos := text.find(mark, match.end())) >= 0),
                default=len(text),
            )
            sentence = text[sentence_start:sentence_end]
            if not _COMMUTE_ROUTINE_RE.search(sentence) or _is_negated_claim(
                sentence, match.end() - sentence_start
            ):
                continue
            origin, destination = match.group("origin", "destination")
            if origin == destination or any(
                cue in sentence
                for cue in ("友人", "友達", "家族", "同僚", "彼", "彼女", "夫", "妻")
            ):
                continue
            if any(
                _mentions_line_name(post.text, line)
                for _op, line in {pair for station in station_records.values() for pair in station}
            ):
                continue
            origin_clue = _matching_text_clue(
                list(clues), post.post_id, f"{origin}駅", ClueType.PLACE_TEXT
            )
            destination_clue = _matching_text_clue(
                list(clues), post.post_id, f"{destination}駅", ClueType.PLACE_TEXT
            )
            if origin_clue is None or destination_clue is None:
                continue
            origin_lines = station_records.get(origin, set())
            destination_lines = station_records.get(destination, set())
            if not origin_lines or not destination_lines:
                continue
            common = origin_lines & destination_lines
            if len(common) != 1:
                continue
            pair = (origin, destination, *next(iter(common)))
            candidates.setdefault(pair, []).append(
                (post, match, origin_clue[0], destination_clue[0])
            )

    output: list[ProfileItem] = []
    for (_origin, _destination, _operator, line), supports in candidates.items():
        # At least two distinct owner-authored posts must independently establish the same pair.
        unique = {support[0].post_id: support for support in supports}
        if len(unique) < 2:
            continue
        evidence = []
        for post, match, origin_index, destination_index in unique.values():
            evidence.extend(
                [
                    ProfileEvidence(
                        post_id=post.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=match.group(0),
                    ),
                    ProfileEvidence(post_id=post.post_id, clue_index=origin_index, required=True),
                    ProfileEvidence(
                        post_id=post.post_id, clue_index=destination_index, required=True
                    ),
                ]
            )
        paths = [
            ProfileEvidencePath(
                evidence=evidence,
                confidence=0.55,
                provenance=EvidencePathProvenance.COMBINED_INFERENCE,
            )
        ]
        flat = evidence
        output.append(
            ProfileItem(
                attribute=ProfileAttribute.REGULAR_LINE,
                value=line,
                confidence=0.55,
                status=ProfileStatus.WEAK,
                evidence=flat,
                evidence_paths=paths,
                assessment=ClaimAssessment(
                    minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                ),
            )
        )
    return output


def _mentions_line_name(text: str, line: str) -> bool:
    return unicodedata.normalize("NFKC", line) in unicodedata.normalize("NFKC", text)


_WORKPLACE_SITE = re.compile(r"(本社|本店|支社|支店|営業所|工場|研究所|キャンパス)")
_WORKPLACE_PREDICATE = re.compile(
    r"(?:働いて(?:いる|います|おり|いた|いました)|勤務して(?:いる|います|おり|いた|いました)|"
    r"勤めて(?:いる|います|おり|いた|いました)|出勤(?:した|している|しています)|"
    r"通勤(?:している|しています))(?=$|[、,。！？\s])"
)
_WORKPLACE_OWNER = re.compile(
    r"(?:私|自分|僕|俺)(?:は|が)[^。！？\n]{0,35}?(?P<org>[一-龯々ぁ-んァ-ヶA-Za-z0-9・＆&（）()ー]+(?:株式会社|有限会社|合同会社|商事|銀行|大学|病院|社))"
    r"[^。！？\n]{0,20}?(?P<site>本社|本店|支社|支店|営業所|工場|研究所|キャンパス)"
    r"[^。！？\n]{0,15}?(?:で|に)?(?:働いて(?:いる|います|おり|いた|いました)|"
    r"勤務して(?:いる|います|おり|いた|いました)|勤めて(?:いる|います|おり|いた|いました))"
    r"(?=$|[、,。！？\s])"
)
_WORKPLACE_ATTENDANCE = re.compile(r"(?:私|自分|僕|俺)(?:は|が)(?P<context>[^。！？\n]{0,90})")
_WORKPLACE_ORG_SITE = re.compile(
    r"(?P<org>[一-龯々ぁ-んァ-ヶA-Za-z0-9・＆&（）()ー]+(?:株式会社|有限会社|合同会社|商事|銀行|大学|病院|社))"
    r"[^。！？\n]{0,25}?(?P<site>本社|本店|支社|支店|営業所|工場|研究所|キャンパス)"
)


def infer_workplace_area_claims(posts: Sequence[Post], clues: Sequence[Clue]) -> list[ProfileItem]:
    """Infer a weak work-area candidate only through the same named employer site in two posts."""
    output: dict[str, ProfileItem] = {}
    for anchor in posts:
        if _forbidden_context(anchor.text) or _has_quoted_or_fiction_context(anchor.text):
            continue
        anchor_match = _WORKPLACE_OWNER.search(anchor.text)
        if anchor_match is None or _is_negated_claim(anchor.text, anchor_match.end()):
            continue
        org, site = anchor_match.group("org", "site")
        for supporting in posts:
            if supporting.post_id == anchor.post_id or _forbidden_context(supporting.text):
                continue
            if _has_quoted_or_fiction_context(supporting.text):
                continue
            owner_match = _WORKPLACE_ATTENDANCE.search(supporting.text)
            if owner_match is None:
                continue
            attendance = owner_match.group("context")
            match = _WORKPLACE_ORG_SITE.search(attendance)
            if (
                match is None
                or _WORKPLACE_PREDICATE.search(attendance) is None
                or _is_negated_claim(supporting.text, owner_match.end())
            ):
                continue
            if (
                _normalize_bridge(match.group("org")) != _normalize_bridge(org)
                or match.group("site") != site
            ):
                continue
            if _third_party_context(
                supporting.text, ProfileAttribute.WORKPLACE_AREA, match.start()
            ):
                continue
            for area_index, area in enumerate(clues):
                if (
                    area.post_id != supporting.post_id
                    or area.type is not ClueType.PLACE_TEXT
                    or area.source not in {ClueSource.OCR, ClueSource.VLM}
                    or area.image_index is None
                    or area.region is None
                    or area.confidence < 0.7
                ):
                    continue
                image = next(
                    (item for item in supporting.images if item.index == area.image_index), None
                )
                if image is None or any(
                    _normalize_bridge(area.value) in _normalize_bridge(p.text)
                    for p in (anchor, supporting)
                ):
                    continue
                # The organization and site must be observable in the same image as the area.
                bridge_clues = [
                    (i, clue)
                    for i, clue in enumerate(clues)
                    if clue.post_id == supporting.post_id
                    and clue.image_index == area.image_index
                    and clue.type is ClueType.ORG_TEXT
                    and clue.source in {ClueSource.OCR, ClueSource.VLM}
                    and clue.region is not None
                    and clue.confidence >= 0.7
                    and (
                        _normalize_bridge(org) in _normalize_bridge(clue.value)
                        or _normalize_bridge(clue.value) in _normalize_bridge(org)
                    )
                    and _normalize_bridge(site) in _normalize_bridge(clue.value)
                    and _regions_linked(area.region, clue.region, image.width, image.height)
                ]
                if not bridge_clues:
                    continue
                area_text = unicodedata.normalize("NFKC", area.value)
                if not _is_residential_value(area_text):
                    continue
                evidence = [
                    ProfileEvidence(
                        post_id=anchor.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=anchor_match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=supporting.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=supporting.post_id,
                        clue_index=area_index,
                        required=True,
                        source="clue",
                    ),
                ]
                for index, _clue in bridge_clues:
                    evidence.append(
                        ProfileEvidence(
                            post_id=supporting.post_id,
                            clue_index=index,
                            required=True,
                            source="clue",
                        )
                    )
                confidence = min(
                    0.65, area.confidence, *(clue.confidence for _, clue in bridge_clues)
                )
                path = ProfileEvidencePath(
                    evidence=evidence,
                    confidence=confidence,
                    provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                )
                key = _normalize_bridge(area.value)
                output.setdefault(
                    key,
                    ProfileItem(
                        attribute=ProfileAttribute.WORKPLACE_AREA,
                        value=area.value,
                        confidence=confidence,
                        status=ProfileStatus.WEAK,
                        evidence=evidence,
                        evidence_paths=[path],
                        assessment=ClaimAssessment(
                            minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                        ),
                    ),
                )
    return list(output.values())


_SHOP_HABIT_CUE = re.compile(r"(?:毎週|毎月|週\s*\d+\s*回|月\s*\d+\s*回|いつも|よく|行きつけ|通い)")
_OWNER_SHOP_HABIT = re.compile(
    r"(?:私|自分|僕|俺)(?:は|が|も)[^、,。！？\n]{0,30}(?:毎週|毎月|週\s*\d+\s*回|月\s*\d+\s*回|いつも|よく|行きつけ|通い)"
)
_SHOP_REFERENCE = re.compile(r"(?:この店|こちらの店|店内|ここ)")
_OWNER_SHOP_VISIT = re.compile(
    r"(?:私|自分|僕|俺)(?:は|が)[^、,。！？\n]{0,30}(?:この店|こちらの店|店内|ここ)"
    r"[^、,。！？\n]{0,20}(?:来|立ち寄|入|利用|休憩|食べ|買|飲|撮|訪れ|過ご|通|寄)"
)
_THIRD_PARTY_SUBJECT = re.compile(r"友人|友達|知人|同僚|他人|家族|甥|姪|彼女|彼氏")
_AMBIGUOUS_SHOP_BRANDS = (
    "スターバックス",
    "スタバ",
    "マクドナルド",
    "マック",
    "モスバーガー",
    "ケンタッキー",
    "吉野家",
    "すき家",
    "松屋",
    "サイゼリヤ",
    "ガスト",
    "コメダ",
    "ドトール",
    "タリーズ",
    "セブンイレブン",
    "ファミリーマート",
    "ローソン",
    "イオン",
)


def infer_frequent_shop_claims(posts: Sequence[Post], clues: Sequence[Clue]) -> list[ProfileItem]:
    """Infer a weak shop candidate only from a separate owner habit and located shop observation.

    The habit post must explicitly refer to ``this shop`` without naming it. A different-day
    post must contain the same typed shop observation, matching place, and an explicit owner
    visit cue. This does not resolve a chain's branch, so known chain names are excluded.
    """
    indexed_clues = [(index, clue) for index, clue in enumerate(clues)]
    claims: dict[str, ProfileItem] = {}
    for habit_post in posts:
        habit_clause = next(
            (
                clause
                for clause in re.split(r"[、,。！？\n]", habit_post.text)
                if _OWNER_SHOP_HABIT.search(clause) and _SHOP_REFERENCE.search(clause)
            ),
            None,
        )
        habit_cue = _OWNER_SHOP_HABIT.search(habit_clause) if habit_clause else None
        if (
            _forbidden_context(habit_post.text)
            or _has_quoted_or_fiction_context(habit_post.text)
            or habit_cue is None
            or _THIRD_PARTY_SUBJECT.search(habit_clause or "")
            or _third_party_context(
                habit_post.text,
                ProfileAttribute.FREQUENT_SHOP,
                habit_post.text.find(habit_clause or ""),
            )
        ):
            continue
        habit_routines = [
            (index, clue)
            for index, clue in indexed_clues
            if clue.post_id == habit_post.post_id
            and clue.type is ClueType.ROUTINE_TEXT
            and clue.confidence >= 0.5
            and _SHOP_HABIT_CUE.search(clue.value)
        ]
        habit_places = [
            (index, clue)
            for index, clue in indexed_clues
            if clue.post_id == habit_post.post_id
            and clue.type is ClueType.PLACE_TEXT
            and clue.confidence >= 0.5
            and clue.value.strip()
            and clue.value.strip() in habit_post.text
            and _is_distinctive_bridge(clue.value)
        ]
        if not habit_routines or not habit_places:
            continue
        habit_shops = [
            (index, clue)
            for index, clue in indexed_clues
            if clue.post_id == habit_post.post_id
            and clue.type is ClueType.SHOP
            and clue.confidence >= 0.5
            and clue.value.strip()
            and "x" not in clue.value.lower()
            and _has_explicit_shop_branch(clue.value)
            and not any(brand in clue.value for brand in _AMBIGUOUS_SHOP_BRANDS)
        ]
        for observation_post in posts:
            if observation_post.post_id == habit_post.post_id:
                continue
            visit_clause = next(
                (
                    clause
                    for clause in re.split(r"[、,。！？\n]", observation_post.text)
                    if _OWNER_SHOP_VISIT.search(clause)
                ),
                None,
            )
            visit_cue = _OWNER_SHOP_VISIT.search(visit_clause) if visit_clause else None
            if (
                _forbidden_context(observation_post.text)
                or _has_quoted_or_fiction_context(observation_post.text)
                or visit_cue is None
                or _THIRD_PARTY_SUBJECT.search(visit_clause or "")
                or _third_party_context(
                    observation_post.text,
                    ProfileAttribute.FREQUENT_SHOP,
                    observation_post.text.find(visit_clause or ""),
                )
            ):
                continue
            if (
                habit_post.created_at is None
                or observation_post.created_at is None
                or habit_post.created_at.date() == observation_post.created_at.date()
            ):
                continue
            observed_places = [
                (index, clue)
                for index, clue in indexed_clues
                if clue.post_id == observation_post.post_id
                and clue.type is ClueType.PLACE_TEXT
                and clue.confidence >= 0.5
                and clue.value.strip()
                and clue.value.strip() in observation_post.text
                and _is_distinctive_bridge(clue.value)
            ]
            shops = [
                (index, clue)
                for index, clue in indexed_clues
                if clue.post_id == observation_post.post_id
                and clue.type is ClueType.SHOP
                and clue.confidence >= 0.5
                and clue.value.strip()
                and "x" not in clue.value.lower()
                and _has_explicit_shop_branch(clue.value)
                and not any(brand in clue.value for brand in _AMBIGUOUS_SHOP_BRANDS)
            ]
            for habit_place_index, habit_place in habit_places:
                for observation_place_index, observation_place in observed_places:
                    if _normalize_bridge(habit_place.value) != _normalize_bridge(
                        observation_place.value
                    ):
                        continue
                    for routine_index, routine in habit_routines:
                        for habit_shop_index, habit_shop in habit_shops:
                            for shop_index, shop in shops:
                                if _normalize_bridge(habit_shop.value) != _normalize_bridge(
                                    shop.value
                                ):
                                    continue
                                value_key = (
                                    unicodedata.normalize("NFKC", shop.value).lower().strip()
                                )
                                # Directly naming the shop in either post collapses this into
                                # self-report, so only retain an independently observed value.
                                if (
                                    shop.value.strip() in habit_post.text
                                    or shop.value.strip() in observation_post.text
                                ):
                                    continue
                                evidence = [
                                    ProfileEvidence(
                                        post_id=habit_post.post_id,
                                        clue_index=None,
                                        required=True,
                                        source="post_text",
                                        excerpt=habit_clause,
                                    ),
                                    ProfileEvidence(
                                        post_id=habit_post.post_id,
                                        clue_index=routine_index,
                                        required=True,
                                        source="clue",
                                    ),
                                    ProfileEvidence(
                                        post_id=habit_post.post_id,
                                        clue_index=habit_place_index,
                                        required=True,
                                        source="clue",
                                    ),
                                    ProfileEvidence(
                                        post_id=habit_post.post_id,
                                        clue_index=habit_shop_index,
                                        required=True,
                                        source="clue",
                                    ),
                                    ProfileEvidence(
                                        post_id=observation_post.post_id,
                                        clue_index=shop_index,
                                        required=True,
                                        source="clue",
                                    ),
                                    ProfileEvidence(
                                        post_id=observation_post.post_id,
                                        clue_index=observation_place_index,
                                        required=True,
                                        source="clue",
                                    ),
                                    ProfileEvidence(
                                        post_id=observation_post.post_id,
                                        clue_index=None,
                                        required=True,
                                        source="post_text",
                                        excerpt=visit_cue.group(0),
                                    ),
                                ]
                                confidence = min(
                                    0.6,
                                    routine.confidence,
                                    habit_place.confidence,
                                    habit_shop.confidence,
                                    shop.confidence,
                                    observation_place.confidence,
                                )
                                if confidence < 0.5:
                                    continue
                                path = ProfileEvidencePath(
                                    evidence=evidence,
                                    confidence=confidence,
                                    provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                                )
                                item = ProfileItem(
                                    attribute=ProfileAttribute.FREQUENT_SHOP,
                                    value=shop.value.strip(),
                                    confidence=confidence,
                                    status=ProfileStatus.WEAK,
                                    evidence=evidence,
                                    evidence_paths=[path],
                                    assessment=ClaimAssessment(
                                        minimal_scope=EvidenceScope.BLUESKY,
                                        harm_status="unknown",
                                    ),
                                )
                                previous = claims.get(value_key)
                                if previous is None or item.confidence > previous.confidence:
                                    claims[value_key] = item
    return list(claims.values())


def _has_explicit_shop_branch(value: str) -> bool:
    """A shop clue needs an observed branch/store marker before it can identify a location."""
    return bool(re.search(r"(?:本店|支店|店|店舗)$", value.strip())) and _is_distinctive_bridge(
        value
    )


_EXPLICIT_CLAIM_RULES: dict[ProfileAttribute, tuple[re.Pattern[str], frozenset[ClueType]]] = {
    ProfileAttribute.FULL_NAME: (
        re.compile(r"(?:私の本名|本名|フルネーム)は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.NAME_TEXT}),
    ),
    ProfileAttribute.GIVEN_NAME: (
        re.compile(r"(?:私の下の名前|下の名前)は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.NAME_TEXT}),
    ),
    ProfileAttribute.NICKNAME: (
        re.compile(r"(?:私のあだ名|ニックネーム|あだ名)は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.NAME_TEXT}),
    ),
    ProfileAttribute.OTHER_SOCIAL_ACCOUNT: (
        re.compile(
            r"(?:私の別垢|私の別アカウント|別垢|別アカウント)は(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.HANDLE_TEXT}),
    ),
    ProfileAttribute.HOME_BUILDING: (
        re.compile(r"(?:私の自宅|自宅|私の家)は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.ADDRESS_TEXT, ClueType.LANDMARK}),
    ),
    ProfileAttribute.HOME_NEAREST_STATION: (
        re.compile(r"(?:自宅|家)(?:の)?最寄り(?:駅)?は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.PLACE_TEXT, ClueType.STATION_SIGN}),
    ),
    ProfileAttribute.REGULAR_LINE: (
        re.compile(r"(?:私の|通勤|通学)(?:で使う)?路線は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.PLACE_TEXT}),
    ),
    ProfileAttribute.ANNOUNCED_LONG_ABSENCE: (
        re.compile(
            r"(?P<value>(?:来週|今週|今月|明日|あす|\d{1,2}月\d{1,2}日)[^。！？\n]{0,24}(?:家|自宅)を(?:空け|留守)[^。！？\n]*)"
        ),
        frozenset({ClueType.ROUTINE_TEXT}),
    ),
    ProfileAttribute.ACTUAL_HOME_ABSENCE: (
        re.compile(r"(?P<value>(?:今|現在)(?:は)?(?:家|自宅)(?:にいません|を空けています))"),
        frozenset({ClueType.ROUTINE_TEXT}),
    ),
    ProfileAttribute.EMPLOYER_NAME: (
        re.compile(r"(?:私の勤務先|勤務先|勤め先|うちの会社)は(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.ORG_TEXT}),
    ),
    ProfileAttribute.WORKPLACE_BUILDING_CANDIDATE: (
        re.compile(
            r"(?:私の|勤務先の|職場の)(?:勤務先|職場)?(?:ビル|建物)は(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.LANDMARK, ClueType.ORG_TEXT}),
    ),
    ProfileAttribute.WORKPLACE_AREA: (
        re.compile(
            r"(?:私の職場|勤務先|職場)の(?:場所|エリア)は(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.PLACE_TEXT}),
    ),
    ProfileAttribute.VEHICLE_MODEL: (
        re.compile(r"(?:私の|自分の|うちの)車(?:は|が)(?P<value>[^、。\s]+?)(?:です|だ|$)"),
        frozenset({ClueType.VEHICLE_MODEL}),
    ),
    ProfileAttribute.PARTIAL_PLATE: (
        re.compile(
            r"(?:私の|自分の|うちの)車の(?:ナンバー|番号)(?:は|が)(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.PLATE}),
    ),
    ProfileAttribute.PARTNER_STATUS: (
        re.compile(
            r"(?:私|自分)(?:は)?(?P<value>既婚|結婚して|交際中|恋人がいる|パートナーがいる)(?:です|だ|$)"
        ),
        frozenset({ClueType.RELATION_TEXT}),
    ),
    ProfileAttribute.PARTNER_ATTRIBUTES: (
        re.compile(
            r"(?:私の|自分の|うちの)(?:夫|妻|配偶者|恋人|パートナー)(?:の|は)(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.AGE_TEXT, ClueType.NAME_TEXT, ClueType.ORG_TEXT}),
    ),
    ProfileAttribute.CHILD_SCHOOL: (
        re.compile(
            r"(?:私の|自分の|うちの)(?:息子|娘|子ども|子供)(?:の学校|の通う学校|の通園先|の通学先)(?:は|が)(?P<value>[^、。\s]+?)(?:です|だ|$)"
        ),
        frozenset({ClueType.ORG_TEXT, ClueType.PLACE_TEXT}),
    ),
}


def infer_explicit_observation_claims(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    *,
    diagnosis_at: datetime | None = None,
) -> list[ProfileItem]:
    """Extract only directly self-associated, typed observations from explicit wording."""
    now = diagnosis_at or datetime.now(UTC)
    claims: dict[tuple[ProfileAttribute, str], ProfileItem] = {}
    self_face_reference = re.compile(r"(?:私|自分)(?:の顔|の自撮り|が撮った自撮り)")
    for post in posts:
        face_match = self_face_reference.search(post.text)
        if (
            face_match is not None
            and not _forbidden_context(post.text)
            and not _has_quoted_or_fiction_context(post.text)
            and not _third_party_context(
                post.text, ProfileAttribute.FACIAL_APPEARANCE, face_match.start()
            )
        ):
            for index, clue in enumerate(clues):
                if (
                    clue.post_id != post.post_id
                    or clue.type is not ClueType.FACE
                    or clue.image_index is None
                    or clue.image_index not in {image.index for image in post.images}
                    or clue.confidence < 0.5
                ):
                    continue
                value = "本人が自分の顔と書いた写真あり"
                confidence = min(0.75, clue.confidence)
                evidence = [
                    ProfileEvidence(
                        post_id=post.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=face_match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=post.post_id, clue_index=index, required=True, source="clue"
                    ),
                ]
                path = ProfileEvidencePath(
                    evidence=evidence,
                    confidence=confidence,
                    provenance=EvidencePathProvenance.DIRECT_DISCLOSURE,
                )
                item = ProfileItem(
                    attribute=ProfileAttribute.FACIAL_APPEARANCE,
                    value=value,
                    confidence=confidence,
                    status=ProfileStatus.WEAK,
                    evidence=evidence,
                    evidence_paths=[path],
                    assessment=ClaimAssessment(
                        minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                    ),
                )
                claims[(ProfileAttribute.FACIAL_APPEARANCE, value)] = item
        for attribute, (pattern, allowed_types) in _EXPLICIT_CLAIM_RULES.items():
            if _forbidden_context(post.text) or _has_quoted_or_fiction_context(post.text):
                continue
            if attribute is ProfileAttribute.ACTUAL_HOME_ABSENCE:
                created_at = post.created_at
                if (
                    created_at is None
                    or created_at.tzinfo is None
                    or created_at.utcoffset() is None
                    or now.tzinfo is None
                    or now.utcoffset() is None
                ):
                    continue
                age = now.astimezone(UTC) - created_at.astimezone(UTC)
                if age < timedelta(0) or age > timedelta(minutes=15):
                    continue
            match = pattern.search(post.text)
            if match is None or _is_negated_claim(post.text, match.end()):
                continue
            if _third_party_context(post.text, attribute, match.start()):
                continue
            captured_value = match.groupdict().get("value")
            if captured_value is None:
                continue
            captured_value = captured_value.removesuffix("です").removesuffix("だ").strip()
            for index, clue in enumerate(clues):
                if clue.post_id != post.post_id or clue.type not in allowed_types:
                    continue
                if clue.confidence < 0.5:
                    continue
                # Candidate values must exactly match the value captured by the self-claim.
                if _normalize_bridge(clue.value) != _normalize_bridge(captured_value):
                    continue
                if attribute is ProfileAttribute.PARTNER_STATUS and not any(
                    token in post.text
                    for token in ("夫", "妻", "恋人", "交際", "パートナー", "結婚", "既婚")
                ):
                    continue
                evidence = [
                    ProfileEvidence(
                        post_id=post.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=post.post_id, clue_index=index, required=True, source="clue"
                    ),
                ]
                confidence = min(0.75, clue.confidence)
                path = ProfileEvidencePath(
                    evidence=evidence,
                    confidence=confidence,
                    provenance=EvidencePathProvenance.DIRECT_DISCLOSURE,
                )
                item = ProfileItem(
                    attribute=attribute,
                    value=clue.value,
                    confidence=confidence,
                    status=ProfileStatus.FOUND,
                    evidence=evidence,
                    evidence_paths=[path],
                    assessment=ClaimAssessment(
                        minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"
                    ),
                )
                key = (attribute, unicodedata.normalize("NFKC", clue.value).lower().strip())
                previous = claims.get(key)
                if previous is None or item.confidence > previous.confidence:
                    claims[key] = item
    return list(claims.values())


def _is_negated_claim(text: str, match_end: int) -> bool:
    """Avoid turning explicit denials or quoted third-party wording into owner claims."""
    if any(mark in text for mark in ("「", "」", "『", "』", "『", "』")):
        return True
    tail = text[match_end : match_end + 36]
    return bool(
        re.search(
            r"(?:ではない|じゃない|ではありません|ではなく|では無い|ではなかった|ではありませんでした|"
            r"しない|しません|しなかった|していない|していません|してなかった)",
            tail,
        )
    )


def _third_party_context(text: str, attribute: ProfileAttribute, match_start: int) -> bool:
    """Reject clauses whose subject is explicitly someone other than the owner."""
    clause_start = max(text.rfind(mark, 0, match_start) for mark in ("。", "！", "？", "\n")) + 1
    left_context = text[clause_start:match_start]
    third_party_subject = re.search(
        r"(?:友人|友達|知人|同僚|他人|家族|甥|姪)(?:の|が|は|という)", left_context
    )
    if third_party_subject:
        return True
    if attribute in {ProfileAttribute.PARTNER_ATTRIBUTES, ProfileAttribute.CHILD_SCHOOL}:
        return False
    return bool(re.search(r"(?:息子|娘|子ども|子供|夫|妻|配偶者|恋人|パートナー)の", left_context))


_REALTIME_LOCATION_RE = re.compile(
    r"(?:現在地(?:は|が)|いま|今)(?:は)?(?P<location>[^、。\s]{2,40}?)(?:にいる|です|なう|$)"
)


def infer_realtime_location_claims(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    *,
    diagnosis_at: datetime | None = None,
) -> list[ProfileItem]:
    """Infer all explicit first-person locations posted within the 15-minute window."""
    now = diagnosis_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("diagnosis_at must be timezone-aware")
    candidates: dict[str, ProfileItem] = {}
    for post in posts:
        created_at = post.created_at
        if created_at is None or created_at.tzinfo is None or created_at.utcoffset() is None:
            continue
        age = now.astimezone(UTC) - created_at.astimezone(UTC)
        if age < timedelta(0) or age > timedelta(minutes=15):
            continue
        if (
            _forbidden_context(post.text)
            or _has_quoted_or_fiction_context(post.text)
            or re.search(r"(?:友達|友人|妻|夫|彼氏|彼女|子ども|子供|息子|娘|甥|姪)が", post.text)
            or re.search(
                r"(?:彼|彼女|友達|友人|妻|夫|子ども|子供|息子|娘|甥|姪)(?:が|は).{0,16}(?:現在地|今|いま)",
                post.text,
            )
        ):
            continue
        match = _REALTIME_LOCATION_RE.search(post.text)
        if not match:
            continue
        location = match.group("location").strip("はがにで、。 ")
        if not location:
            continue
        typed = _matching_text_clue(list(clues), post.post_id, location, ClueType.PLACE_TEXT)
        if typed is None:
            continue
        clue_index, clue = typed
        confidence = min(0.75, clue.confidence)
        if confidence < 0.5:
            continue
        evidence = [
            ProfileEvidence(
                post_id=post.post_id,
                clue_index=None,
                required=True,
                source="post_text",
                excerpt=match.group(0),
            ),
            ProfileEvidence(
                post_id=post.post_id, clue_index=clue_index, required=True, source="clue"
            ),
        ]
        path = ProfileEvidencePath(
            evidence=evidence,
            confidence=confidence,
            provenance=EvidencePathProvenance.DIRECT_DISCLOSURE,
        )
        normalized = unicodedata.normalize("NFKC", location).lower()
        candidates[normalized] = ProfileItem(
            attribute=ProfileAttribute.REALTIME_LOCATION,
            value=location,
            confidence=confidence,
            status=ProfileStatus.FOUND,
            evidence=evidence,
            evidence_paths=[path],
            assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"),
        )
    return list(candidates.values())


def infer_realtime_location_claim(
    posts: Sequence[Post], clues: Sequence[Clue], *, diagnosis_at: datetime | None = None
) -> ProfileItem | None:
    """Backward-compatible singular helper; ambiguous locations return no winner."""
    candidates = infer_realtime_location_claims(posts, clues, diagnosis_at=diagnosis_at)
    return candidates[0] if len(candidates) == 1 else None


_SCHOOL_SUFFIX = re.compile(r"(?:大学|高等学校|高校|高専|専門学校|中学校|中学|学校)$")
_SCHOOL_CONTEXT = re.compile(r"大学|高校|高専|専門学校|中学校|学校|キャンパス|学園")
_CLASS_CONTEXT = re.compile(
    r"(?:授業|講義)\s*(?:終わり|おわり|後|のあと|が終わ|終わった|受け|に行|ある|中)"
)
_FESTIVAL_CONTEXT = re.compile(
    r"(?:(?:近づ|近付|ちかづ|迫っ|もうすぐ|間近|来週|今週|まもなく).{0,8}"
    r"(?:文化祭|学園祭|大学祭)|(?:文化祭|学園祭|大学祭).{0,8}"
    r"(?:近づ|近付|ちかづ|迫っ|もうすぐ|間近|来週|今週|まもなく|開催))"
)
_SCHOOL_STAFF_OR_VISIT = re.compile(
    r"(?:教員|先生|講師|教授|教師|職員|スタッフ|非常勤|教える|授業を担当|"
    r"訪問|見学|遊びに|guest|visitor|visit-only)",
    re.IGNORECASE,
)
_SCHOOL_MENTION = re.compile(
    r"[\wぁ-んァ-ヶ一-龠々・]{2,30}(?:大学|高等学校|高校|高専|専門学校|中学校|中学|学校)"
)


def infer_school_claims(posts: list[Post], clues: list[Clue]) -> list[ProfileItem]:
    """Infer a weak school-affiliation candidate from an image observation and two posts.

    The named institution must be an exact OCR/VLM organization clue in a post whose text
    independently mentions a school or campus. Different posts must then describe the owner's
    own class context and an upcoming school festival. Visitor/staff and competing-school
    contexts are rejected. The pattern is deliberately conservative and does not establish
    student status.
    """
    post_by_id = {post.post_id: post for post in posts}
    school_signs: dict[str, list[tuple[int, Clue, Post]]] = {}
    for index, clue in enumerate(clues):
        post = post_by_id.get(clue.post_id)
        name = unicodedata.normalize("NFKC", clue.value).strip()
        if (
            post is None
            or clue.type is not ClueType.ORG_TEXT
            or clue.source not in {ClueSource.OCR, ClueSource.VLM}
            or clue.image_index is None
            or clue.confidence < 0.85
            or not _SCHOOL_SUFFIX.search(name)
            or not _SCHOOL_CONTEXT.search(post.text)
            or _SCHOOL_STAFF_OR_VISIT.search(post.text)
            or _forbidden_context(post.text)
        ):
            continue
        school_signs.setdefault(name, []).append((index, clue, post))
    if not school_signs:
        return []
    if len(school_signs) > 1:
        return [
            claim
            for school_name in school_signs
            for claim in infer_school_claims(
                posts,
                [
                    clue
                    for clue in clues
                    if unicodedata.normalize("NFKC", clue.value).strip() == school_name
                ],
            )
        ]
    school_name, signs = next(iter(school_signs.items()))
    anchor_post_ids = {post.post_id for _, _, post in signs}

    def mentions_other_school(text: str) -> bool:
        mentions = {
            unicodedata.normalize("NFKC", match.group(0)).strip()
            for match in _SCHOOL_MENTION.finditer(text)
        }
        return any(mention != school_name for mention in mentions)

    class_posts = [
        post
        for post in posts
        if post.post_id not in anchor_post_ids
        and _CLASS_CONTEXT.search(post.text)
        and not _SCHOOL_STAFF_OR_VISIT.search(post.text)
        and not _forbidden_context(post.text)
        and not mentions_other_school(post.text)
    ]
    festival_posts = [
        post
        for post in posts
        if post.post_id not in anchor_post_ids
        and _FESTIVAL_CONTEXT.search(post.text)
        and not _SCHOOL_STAFF_OR_VISIT.search(post.text)
        and not _forbidden_context(post.text)
        and not mentions_other_school(post.text)
    ]
    paths: list[ProfileEvidencePath] = []
    for clue_index, _, anchor_post in signs:
        anchor_context = _SCHOOL_CONTEXT.search(anchor_post.text)
        if anchor_context is None:
            continue
        for class_post in class_posts:
            for festival_post in festival_posts:
                if festival_post.post_id in {anchor_post.post_id, class_post.post_id}:
                    continue
                class_match = _CLASS_CONTEXT.search(class_post.text)
                festival_match = _FESTIVAL_CONTEXT.search(festival_post.text)
                if class_match is None or festival_match is None:
                    continue
                evidence = [
                    ProfileEvidence(
                        post_id=anchor_post.post_id,
                        clue_index=clue_index,
                        required=True,
                        source="clue",
                    ),
                    ProfileEvidence(
                        post_id=anchor_post.post_id,
                        required=True,
                        source="post_text",
                        excerpt=anchor_context.group(0),
                    ),
                    ProfileEvidence(
                        post_id=class_post.post_id,
                        required=True,
                        source="post_text",
                        excerpt=class_match.group(0),
                    ),
                    ProfileEvidence(
                        post_id=festival_post.post_id,
                        required=True,
                        source="post_text",
                        excerpt=festival_match.group(0),
                    ),
                ]
                path = ProfileEvidencePath(
                    evidence=evidence,
                    confidence=0.55,
                    provenance=EvidencePathProvenance.COMBINED_INFERENCE,
                )
                paths.append(path)
    if not paths:
        return []
    unique_paths = {
        tuple(
            (
                reference.source.value,
                reference.post_id or "",
                reference.clue_index,
                reference.excerpt or "",
            )
            for reference in path.evidence
        ): path
        for path in paths
    }
    paths = list(unique_paths.values())
    return [
        ProfileItem(
            attribute=ProfileAttribute.SCHOOL,
            value=school_name,
            confidence=0.55,
            status=ProfileStatus.WEAK,
            evidence=[reference for path in paths for reference in path.evidence],
            evidence_paths=paths,
            assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY, harm_status="unknown"),
        )
    ]


def infer_school_claim(posts: list[Post], clues: list[Clue]) -> ProfileItem | None:
    """Backward-compatible singular helper; no school is arbitrarily selected."""
    claims = infer_school_claims(posts, clues)
    return claims[0] if len(claims) == 1 else None


_CHILD_BIRTH_YEAR_RE = re.compile(
    r"(?P<relation>息子|娘|子ども|子供)の(?P<name>[\wぁ-んァ-ヶ一-龠]{2,12})(?:は|が|、|\s)"
    r"(?P<year>20\d{2})年生まれ"
)
_CHILD_BIRTHDAY_RE = re.compile(
    r"(?P<relation>息子|娘|子ども|子供)の(?P<name>[\wぁ-んァ-ヶ一-龠]{2,12})(?:は|が|、|\s)"
    r"(?:今日は|本日は|今日|本日)(?:誕生日|お誕生日)"
)
_CHILD_EXPLICIT_AGE_RE = re.compile(r"(?:息子|娘|子ども|子供)[^。！？\n]{0,30}?(?P<age>\d{1,2})歳")
_CHILD_AGE_EXCLUDED_RE = re.compile(
    r"(?:甥|姪|友達|友人|知人|親戚|親族|同僚|他人|架空|創作|小説|アニメ|キャラ|想像|もしも|引用|リポスト|RT|引用投稿|"
    r"元夫|元妻|元旦那|元嫁|元パートナー|離婚|別居|亡くな|死去|生まれていない|"
    r"誕生日ではない|誕生日じゃない|誕生日ではありません|誕生日じゃありません)"
)

JAPAN_TZ = timezone(timedelta(hours=9))


def infer_child_age_claims(
    posts: list[Post], diagnosis_date: date | None = None
) -> list[ProfileItem]:
    """Infer an exact current child age only from two independent, owner-authored posts.

    One post links a distinctive child name to a birth year; a different post links
    the same child to a birthday on the post's local calendar date. Requiring both
    prevents either post alone from disclosing the exact current age.
    """
    today = diagnosis_date or datetime.now(JAPAN_TZ).date()
    birth_year_posts: dict[tuple[str, str, int], list[tuple[Post, str]]] = {}
    birthday_posts: dict[tuple[str, str], list[tuple[Post, date, str]]] = {}
    explicitly_disclosed_child_age = False
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        if _CHILD_AGE_EXCLUDED_RE.search(text) or _has_quoted_or_fiction_context(text):
            continue
        explicitly_disclosed_child_age |= bool(_CHILD_EXPLICIT_AGE_RE.search(text))
        for match in _CHILD_BIRTH_YEAR_RE.finditer(text):
            name = _normalize_bridge(match.group("name"))
            year = int(match.group("year"))
            if _distinctive_child_name(name) and year <= today.year:
                birth_year_posts.setdefault((match.group("relation"), name, year), []).append(
                    (post, match.group(0))
                )
        for match in _CHILD_BIRTHDAY_RE.finditer(text):
            name = _normalize_bridge(match.group("name"))
            if _distinctive_child_name(name):
                birthday_posts.setdefault((match.group("relation"), name), []).append(
                    (post, post.created_at.astimezone(JAPAN_TZ).date(), match.group(0))
                )

    candidates: list[tuple[int, Post, str, Post, str]] = []
    for (relation, name, birth_year), birth_records in birth_year_posts.items():
        if explicitly_disclosed_child_age:
            continue
        for birthday_post, birthday, birthday_excerpt in birthday_posts.get((relation, name), []):
            if birthday > today or birthday.year <= birth_year:
                continue
            if birthday.month == 2 and birthday.day == 29:
                # Leap-day birthdays have differing anniversary conventions; do not guess.
                continue
            age = (
                today.year
                - birth_year
                - ((today.month, today.day) < (birthday.month, birthday.day))
            )
            if not 0 <= age <= 17:
                continue
            distinct_birth_records = [
                (post, excerpt)
                for post, excerpt in birth_records
                if post.post_id != birthday_post.post_id
            ]
            for birth_post, birth_excerpt in distinct_birth_records:
                candidates.append((age, birth_post, birth_excerpt, birthday_post, birthday_excerpt))

    if not candidates:
        return []
    confidence = 0.55  # provisional rule strength; not a calibrated probability
    paths_by_age: dict[int, list[ProfileEvidencePath]] = {}
    for age, birth_post, birth_excerpt, birthday_post, birthday_excerpt in candidates:
        path = ProfileEvidencePath(
            evidence=[
                ProfileEvidence(
                    post_id=birth_post.post_id,
                    required=True,
                    source="post_text",
                    excerpt=birth_excerpt,
                ),
                ProfileEvidence(
                    post_id=birthday_post.post_id,
                    required=True,
                    source="post_text",
                    excerpt=birthday_excerpt,
                ),
            ],
            confidence=confidence,
            provenance=EvidencePathProvenance.COMBINED_INFERENCE,
        )
        paths_by_age.setdefault(age, []).append(path)
    return [
        ProfileItem(
            attribute=ProfileAttribute.CHILD_AGE,
            value=f"{age}歳",
            confidence=confidence,
            status=ProfileStatus.WEAK,
            evidence=[ref for path in paths for ref in path.evidence],
            evidence_paths=paths,
            assessment=ClaimAssessment(
                minimal_scope=EvidenceScope.BLUESKY,
                harm_status="prerequisites_unmet",
                harm_scenario="子どもの年齢と識別情報が組み合わさると、保護者や子どもを狙うなりすまし・詐欺の説得材料になりうる",
                harm_prerequisites=[
                    "子どもを識別できる情報が別途得られる",
                    "攻撃者がその情報を悪用する",
                ],
            ),
        )
        for age, paths in sorted(paths_by_age.items())
    ]


def infer_child_age_claim(
    posts: list[Post], diagnosis_date: date | None = None
) -> ProfileItem | None:
    """Backward-compatible singular helper; competing ages have no arbitrary winner."""
    claims = infer_child_age_claims(posts, diagnosis_date=diagnosis_date)
    return claims[0] if len(claims) == 1 else None


def _distinctive_child_name(name: str) -> bool:
    return len(name) >= 2 and name not in {
        "子ども",
        "こども",
        "子供",
        "むすこ",
        "むすめ",
        "長男",
        "次男",
        "三男",
        "長女",
        "次女",
        "三女",
    }


def _has_quoted_or_fiction_context(text: str) -> bool:
    # Treat any quoted segment as untrusted attribution. This is deliberately
    # conservative for apostrophes: a false negative could assign another
    # person's statement to the owner for sensitive fields.
    return any(mark in text for mark in ("「", "」", "『", "』", "“", "”", '"', "'", "引用"))


REGULAR_STATION_MIN_OCR_CONFIDENCE = 0.8
REGULAR_STATION_ANCHOR_CONFIDENCE = 0.65
REGULAR_STATION_REFERENCE_RE = re.compile(
    r"(?:いつもの通勤駅(?:を使|を利用|から通勤)|いつも使う通勤駅|いつも利用する通勤駅|"
    r"通勤でいつも使う駅|通勤でいつも利用する駅|"
    r"(?:毎日|毎朝|平日は|普段)(?:の)?通勤で使う駅|通勤で(?:毎日|毎朝|平日は|普段)使う駅)"
)
REGULAR_STATION_CONTEXT_RE = re.compile(
    r"(?:いつもの通勤駅|いつも使う通勤駅|いつも利用する通勤駅|通勤でいつも使う駅|"
    r"通勤でいつも利用する駅|(?:毎日|毎朝|平日は|普段)(?:の)?通勤で使う駅|"
    r"通勤で(?:毎日|毎朝|平日は|普段)使う駅)(?:から|で|を使|を利用)"
)
REGULAR_STATION_BRIDGE_ID = "regular_station:usual_commute"
HOME_STATION_MIN_CONFIDENCE = 0.8
HOME_STATION_ANCHOR_RE = re.compile(r"(?:私|自分|うち)(?:の)?自宅の最寄り駅")
HOME_STATION_ROUTINE_RE = re.compile(
    r"(?:私|自分|僕|俺)(?:は|が)[^。！？\n]{0,30}自宅から駅まで[^。！？\n]{0,20}(?:毎朝|毎日|平日は|いつも|普段)"
)


def infer_home_nearest_station_claims(
    posts: list[Post], clues: list[Clue], gazetteer: Gazetteer
) -> list[ProfileItem]:
    """Infer home-nearest stations from a self-owned unnamed relation and routine."""
    known_names = {
        unicodedata.normalize("NFKC", row["station_name"]).strip()
        for row in gazetteer.stations
        if isinstance(row.get("station_name"), str) and row["station_name"].strip()
    }
    if not known_names:
        return []
    facts: list[CrossPostFact] = []
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        if (
            _forbidden_context(text)
            or _has_quoted_or_fiction_context(text)
            or not HOME_STATION_ANCHOR_RE.search(text)
        ):
            continue
        if any(_mentions_station_name(text, name) for name in known_names):
            continue
        # A caption saying only that the sign is at a station is not a home relation.
        if not any(cue in text for cue in ("写真", "駅名標", "看板", "標識", "ここ")):
            continue
        for ocr_index, ocr in enumerate(clues):
            if (
                ocr.post_id != post.post_id
                or ocr.type is not ClueType.STATION_SIGN
                or ocr.source is not ClueSource.OCR
                or ocr.image_index is None
                or ocr.image_index >= len(post.images)
                or ocr.region is None
                or ocr.confidence < HOME_STATION_MIN_CONFIDENCE
                or "x" in ocr.value.lower()
            ):
                continue
            station = unicodedata.normalize("NFKC", ocr.value).removesuffix("駅").strip()
            if station not in known_names:
                continue
            corroborators = [
                (index, clue)
                for index, clue in enumerate(clues)
                if clue.post_id == post.post_id
                and clue.type is ClueType.STATION_SIGN
                and clue.source is ClueSource.VLM
                and clue.image_index == ocr.image_index
                and clue.region is not None
                and clue.confidence >= HOME_STATION_MIN_CONFIDENCE
                and unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip() == station
                and _regions_overlap(ocr.region, clue.region)
            ]
            if not corroborators:
                continue
            vlm_index, _ = corroborators[0]
            anchor_match = HOME_STATION_ANCHOR_RE.search(text)
            if anchor_match is None:
                continue
            facts.append(
                CrossPostFact(
                    post_id=post.post_id,
                    clue_index=ocr_index,
                    role=FactRole.SPECIFIC_VALUE,
                    value=station,
                    confidence=min(ocr.confidence, REGULAR_STATION_ANCHOR_CONFIDENCE),
                    bridge_id="home_station:self_nearest",
                    excerpt=ocr.value,
                    source="clue",
                    related_evidence=(
                        ProfileEvidence(post_id=post.post_id, clue_index=vlm_index, required=True),
                        ProfileEvidence(
                            post_id=post.post_id,
                            clue_index=None,
                            required=True,
                            source="post_text",
                            excerpt=anchor_match.group(0),
                        ),
                    ),
                )
            )
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        match = HOME_STATION_ROUTINE_RE.search(text)
        if not match or _forbidden_context(text) or _has_quoted_or_fiction_context(text):
            continue
        if any(_mentions_station_name(text, name) for name in known_names):
            continue
        routine_clues = [
            (index, clue)
            for index, clue in enumerate(clues)
            if clue.post_id == post.post_id
            and clue.type is ClueType.ROUTINE_TEXT
            and clue.source is ClueSource.TEXT
            and clue.value.strip() in text
            and HOME_STATION_ROUTINE_RE.search(clue.value)
        ]
        if not routine_clues:
            continue
        facts.append(
            CrossPostFact(
                post_id=post.post_id,
                clue_index=None,
                role=FactRole.OWNER_RELATION,
                value="自宅から駅までの習慣",
                confidence=REGULAR_STATION_ANCHOR_CONFIDENCE,
                bridge_id="home_station:self_nearest",
                owner_relation_explicit=True,
                excerpt=match.group(0),
                source="post_text",
                related_evidence=tuple(
                    ProfileEvidence(post_id=post.post_id, clue_index=index, required=True)
                    for index, _ in routine_clues
                ),
            )
        )
    claims = infer_cross_post_candidates(ProfileAttribute.HOME_NEAREST_STATION, facts)
    return [claim.model_copy(update={"value": f"{claim.value}駅"}) for claim in claims]


def infer_regular_station_claims(
    posts: list[Post],
    clues: list[Clue],
    gazetteer: Gazetteer,
) -> list[ProfileItem]:
    """Infer each separately grounded commute-station candidate from linked OCR signs."""
    known_names = {
        unicodedata.normalize("NFKC", row["station_name"]).strip()
        for row in gazetteer.stations
        if isinstance(row.get("station_name"), str) and row["station_name"].strip()
    }
    if not known_names:
        return []

    facts: list[CrossPostFact] = []
    for post in posts:
        normalized_text = unicodedata.normalize("NFKC", post.text)
        if (
            not _has_regular_commute_habit(normalized_text)
            or _forbidden_context(normalized_text)
            or any(_mentions_station_name(normalized_text, name) for name in known_names)
        ):
            continue
        routine_clues = [
            (index, clue)
            for index, clue in enumerate(clues)
            if clue.post_id == post.post_id
            and clue.type is ClueType.ROUTINE_TEXT
            and clue.source is ClueSource.TEXT
            and _has_regular_commute_habit(clue.value)
            and not any(_mentions_station_name(clue.value, name) for name in known_names)
            and unicodedata.normalize("NFKC", clue.value).strip() in normalized_text
        ]
        fact = CrossPostFact(
            post_id=post.post_id,
            clue_index=None,
            role=FactRole.OWNER_RELATION,
            value="いつもの通勤駅",
            confidence=REGULAR_STATION_ANCHOR_CONFIDENCE,
            bridge_id=REGULAR_STATION_BRIDGE_ID,
            owner_relation_explicit=True,
            excerpt=normalized_text,
            source="post_text",
            related_evidence=tuple(
                ProfileEvidence(
                    post_id=post.post_id,
                    clue_index=index,
                    required=True,
                )
                for index, _ in routine_clues
            ),
        )
        facts.append(fact)

    for post in posts:
        if not REGULAR_STATION_CONTEXT_RE.search(post.text) or _forbidden_context(post.text):
            continue
        post_station_clues = [
            clue
            for clue in clues
            if clue.post_id == post.post_id and clue.type is ClueType.STATION_SIGN
        ]
        if any("x" in clue.value.lower() for clue in post_station_clues):
            continue
        observed_values = {
            unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip()
            for clue in post_station_clues
            if clue.value.strip()
        }
        # Station signs often contain the adjacent stations. Any distinct value
        # makes the photographed sign ambiguous, even if one clue is OCR-derived.
        if len(observed_values) != 1:
            continue
        station = next(iter(observed_values))
        ocr_matches = [
            (index, clue)
            for index, clue in enumerate(clues)
            if clue.post_id == post.post_id
            and clue.type is ClueType.STATION_SIGN
            and clue.source is ClueSource.OCR
            and clue.image_index is not None
            and clue.image_index < len(post.images)
            and clue.region is not None
            and clue.confidence >= REGULAR_STATION_MIN_OCR_CONFIDENCE
            and "x" not in clue.value.lower()
            and unicodedata.normalize("NFKC", clue.value).removesuffix("駅").strip() == station
            and station in known_names
        ]
        if not ocr_matches:
            continue
        if any(_mentions_station_name(post.text, name) for name in known_names):
            continue
        corroborated = []
        for ocr_index, ocr_clue in ocr_matches:
            for vlm_index, vlm_clue in enumerate(clues):
                if (
                    vlm_clue.post_id != post.post_id
                    or vlm_clue.type is not ClueType.STATION_SIGN
                    or vlm_clue.source is not ClueSource.VLM
                    or vlm_clue.image_index != ocr_clue.image_index
                    or ocr_clue.region is None
                    or vlm_clue.region is None
                    or vlm_clue.confidence < REGULAR_STATION_MIN_OCR_CONFIDENCE
                    or unicodedata.normalize("NFKC", vlm_clue.value).removesuffix("駅").strip()
                    != station
                    or not _regions_overlap(ocr_clue.region, vlm_clue.region)
                ):
                    continue
                corroborated.append((ocr_index, ocr_clue, vlm_index))
        if not corroborated:
            continue
        clue_index, clue, vlm_index = corroborated[0]
        context = REGULAR_STATION_CONTEXT_RE.search(post.text)
        facts.append(
            CrossPostFact(
                post_id=post.post_id,
                clue_index=clue_index,
                role=FactRole.SPECIFIC_VALUE,
                value=station,
                confidence=min(clue.confidence, REGULAR_STATION_ANCHOR_CONFIDENCE),
                bridge_id=REGULAR_STATION_BRIDGE_ID,
                excerpt=clue.value,
                source="clue",
                related_evidence=(
                    ProfileEvidence(post_id=post.post_id, clue_index=vlm_index, required=True),
                    ProfileEvidence(
                        post_id=post.post_id,
                        clue_index=None,
                        required=True,
                        source="post_text",
                        excerpt=context.group(0) if context else post.text,
                    ),
                ),
            )
        )

    claims = infer_cross_post_candidates(ProfileAttribute.REGULAR_STATION, facts)
    return [claim.model_copy(update={"value": f"{claim.value}駅"}) for claim in claims]


def infer_regular_station_claim(
    posts: list[Post], clues: list[Clue], gazetteer: Gazetteer
) -> ProfileItem | None:
    """Backward-compatible singular helper; competing stations have no arbitrary winner."""
    claims = infer_regular_station_claims(posts, clues, gazetteer)
    return claims[0] if len(claims) == 1 else None


def _has_regular_commute_habit(text: str) -> bool:
    """Require a habitual/deictic commute-station phrase, not generic station use."""
    normalized = unicodedata.normalize("NFKC", text)
    sentences = re.split(r"[。！？!?\n]", normalized)
    return any(REGULAR_STATION_REFERENCE_RE.search(sentence) for sentence in sentences)


def _mentions_station_name(text: str, station: str) -> bool:
    """Treat a station name followed by 駅 as already disclosed in the text."""
    return f"{station}駅" in unicodedata.normalize("NFKC", text)


def _regions_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return left[0] < right[2] and right[0] < left[2] and left[1] < right[3] and right[1] < left[3]


def _regions_linked(
    left: tuple[int, int, int, int], right: tuple[int, int, int, int], width: int, height: int
) -> bool:
    """Accept overlap or <= max(24 px, 2% of the longest image edge) rectangle gap."""
    if _regions_overlap(left, right):
        return True
    gap_x = max(0, left[0] - right[2], right[0] - left[2])
    gap_y = max(0, left[1] - right[3], right[1] - left[3])
    threshold = max(24, round(max(width, height) * 0.02))
    return max(gap_x, gap_y) <= threshold


def _matching_profile_clue(clues: list[Clue], value: str, clue_type: ClueType) -> Clue | None:
    return next(
        (
            clue
            for clue in clues
            if clue.source is ClueSource.PROFILE_TEXT
            and clue.type is clue_type
            and _normalize_bridge(clue.value) == _normalize_bridge(value)
        ),
        None,
    )


def _is_residential_value(value: str) -> bool:
    return value.endswith(("市", "区", "町", "村", "郡", "丁目", "団地", "エリア"))


def _is_organization_name(value: str) -> bool:
    normalized = value.strip()
    legal_prefixes = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社")
    if any(
        normalized.startswith(prefix) and len(normalized.removeprefix(prefix)) >= 2
        for prefix in legal_prefixes
    ):
        return True
    return normalized.endswith(
        (
            "社",
            "株式会社",
            "有限会社",
            "合同会社",
            "合資会社",
            "合名会社",
            "商事",
            "銀行",
            "大学",
            "法人",
        )
    )
