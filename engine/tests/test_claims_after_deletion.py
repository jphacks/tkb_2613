"""消した投稿を根拠から除いたプロフィール推定（画面の profileClaimsAfterDeletion と同じ規則）。"""

from tkb_common.schemas import (
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
)
from tkb_engine.cross_post import claims_after_deletion

A, B, C = (f"at://did:plc:me/app.bsky.feed.post/{x}" for x in "abc")


def _evidence(post_id: str, index: int) -> ProfileEvidence:
    return ProfileEvidence(post_id=post_id, clue_index=index, required=True)


def _with_paths(*paths: tuple[str, str], confidence: float = 0.85) -> ProfileItem:
    evidence_paths = [
        ProfileEvidencePath(evidence=[_evidence(a, 0), _evidence(b, 1)], confidence=confidence)
        for a, b in paths
    ]
    return ProfileItem(
        attribute=ProfileAttribute.RESIDENTIAL_AREA,
        value="文京区",
        confidence=confidence,
        status=ProfileStatus.FOUND,
        evidence=[e for path in evidence_paths for e in path.evidence],
        evidence_paths=evidence_paths,
    )


def _without_paths(post_id: str) -> ProfileItem:
    return ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value="架空商事",
        confidence=0.9,
        status=ProfileStatus.FOUND,
        evidence=[_evidence(post_id, 0)],
    )


def test_nothing_deleted_keeps_every_claim() -> None:
    claims = [_with_paths((A, B)), _without_paths(C)]
    assert claims_after_deletion(claims, set()) == claims


def test_claim_whose_only_path_was_deleted_is_dropped() -> None:
    assert claims_after_deletion([_with_paths((A, B))], {A}) == []


def test_claim_keeps_only_the_surviving_path() -> None:
    [after] = claims_after_deletion([_with_paths((A, B), (B, C))], {A})
    assert [[e.post_id for e in path.evidence] for path in after.evidence_paths] == [[B, C]]
    assert all(e.post_id != A for e in after.evidence)


def test_claim_without_paths_is_dropped_only_when_its_evidence_was_deleted() -> None:
    claim = _without_paths(C)
    assert claims_after_deletion([claim], {A}) == [claim]
    assert claims_after_deletion([claim], {C}) == []
