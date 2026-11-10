"""Conservative claim paths for residential-area and employer inference."""

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata
from itertools import combinations

from tkb_common.schemas import (
    ClaimAssessment,
    Clue,
    ClueSource,
    ClueType,
    EvidenceScope,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
    Post,
    WebFact,
    WebSourceKind,
    WebVerificationStatus,
)


class FactRole(StrEnum):
    OWNER_RELATION = "owner_relation"
    SPECIFIC_VALUE = "specific_value"
    BRIDGE = "bridge"


@dataclass(frozen=True)
class CrossPostFact:
    post_id: str | None
    clue_index: int | None
    role: FactRole
    value: str
    confidence: float
    # An explicit phrase, identifier, or other observed bridge connecting this fact to the
    # same owner-related entity. Do not use a mere visit, logo, or location coincidence.
    bridge_id: str | None
    owner_relation_explicit: bool = False
    context: str = ""
    excerpt: str = ""
    related_evidence: tuple[ProfileEvidence, ...] = ()
    source: str = "post_text"


def infer_cross_post_claim(
    attribute: ProfileAttribute,
    facts: list[CrossPostFact],
) -> ProfileItem | None:
    """Build only unambiguous AND paths spanning at least two independent posts.

    Each successful path needs one explicit owner-relation fact and one value fact, in
    different posts, joined by the same explicit bridge. Any competing value invalidates the
    claim instead of choosing one. Confidence is the weakest fact on the AND path.
    """
    if attribute not in {ProfileAttribute.RESIDENTIAL_AREA, ProfileAttribute.EMPLOYER_NAME}:
        raise ValueError("cross-post gate is only defined for residential_area and employer_name")
    expected_bridge = "home:" if attribute is ProfileAttribute.RESIDENTIAL_AREA else "employer:"
    eligible = [
        f for f in facts
        if f.value.strip() and f.bridge_id and f.bridge_id.startswith(expected_bridge) and not _forbidden_context(f.context)
    ]
    anchors = [f for f in eligible if f.role is FactRole.OWNER_RELATION and f.owner_relation_explicit]
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
            key = value_fact.value.strip().casefold()
            candidates[key] = value_fact.value.strip()
            if anchor.post_id is not None and value_fact.post_id is not None:
                paths.append([anchor, value_fact])
            else:
                required_post_ids = {f.post_id for f in (anchor, value_fact) if f.post_id is not None}
                bridge_posts = [f for f in bridges if f.bridge_id == anchor.bridge_id and f.post_id is not None and f.post_id not in required_post_ids]
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
        signature = tuple(sorted((f.source, f.post_id or "", f.clue_index if f.clue_index is not None else -1, f.role.value, f.bridge_id or "", f.value, f.excerpt) for f in path))
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
        status=ProfileStatus.FOUND if confidence >= 0.8 else ProfileStatus.WEAK,
        evidence=flat_evidence,
        evidence_paths=evidence_paths,
        assessment=ClaimAssessment(
            minimal_scope=EvidenceScope.BLUESKY,
            harm_status="unknown",
        ),
    )


def recalculate_after_deletion(item: ProfileItem, deleted_post_ids: set[str]) -> ProfileItem | None:
    """Keep only complete alternative proof paths that survive post deletion."""
    surviving = [
        path for path in item.evidence_paths
        if not any(reference.post_id in deleted_post_ids for reference in path.evidence)
    ]
    if not surviving:
        return None
    confidence = max(path.confidence for path in surviving)
    if confidence < 0.5:
        return None
    return item.model_copy(update={
        "evidence_paths": surviving,
        "evidence": [e for path in surviving for e in path.evidence],
        "confidence": confidence,
        "status": ProfileStatus.FOUND if confidence >= 0.8 else ProfileStatus.WEAK,
        "assessment": item.assessment.model_copy(update={"minimal_scope": _minimal_scope(surviving)}),
    })


def _minimal_scope(paths: list[ProfileEvidencePath]) -> EvidenceScope:
    return (
        EvidenceScope.BLUESKY
        if any(all(ref.source != "public_web" for ref in path.evidence) for path in paths)
        else EvidenceScope.BLUESKY_PUBLIC_WEB
    )


def infer_web_employer_claim(
    posts: list[Post], web_facts: list[WebFact], owner_profile_text: str = "",
) -> ProfileItem | None:
    """Infer an employer from explicit employer naming, a second owner post, and a verified legal name.

    The explicit employer anchor identifies the owner relationship; the public source only
    normalizes that named organization to its legal name.
    """
    candidates: dict[str, tuple[str, list[ProfileEvidencePath]]] = {}
    anchors = [(post.post_id, post.text, "post_text") for post in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    eligible_facts = [
        fact for fact in web_facts
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
                    if supporting_post.post_id == anchor_post_id or bridge_text not in supporting_post.text:
                        continue
                    if _forbidden_context(supporting_post.text):
                        continue
                    # Profile anchors still require two independent posts.
                    if anchor_post_id is None:
                        other_posts = [
                            post for post in posts
                            if post.post_id != supporting_post.post_id and bridge_text in post.text
                        ]
                    else:
                        other_posts = [next(post for post in posts if post.post_id == anchor_post_id)]
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
                                post_id=other_post.post_id if anchor_post_id is None else supporting_post.post_id,
                                clue_index=None,
                                required=True,
                                source="post_text",
                                excerpt=bridge_text,
                            ),
                            ProfileEvidence(
                                source="public_web", web_fact_id=fact.id, required=True,
                            ),
                        ]
                        if anchor_post_id is None:
                            evidence.insert(2, ProfileEvidence(
                                post_id=supporting_post.post_id, clue_index=None, required=True,
                                source="post_text", excerpt=bridge_text,
                            ))
                        key = _normalize_bridge(fact.object)
                        candidates.setdefault(key, (fact.object, []))[1].append(
                            ProfileEvidencePath(evidence=evidence, confidence=0.65)
                        )
    if len(candidates) != 1:
        return None
    value, paths = next(iter(candidates.values()))
    unique_paths: dict[tuple[tuple[str, str, str], ...], ProfileEvidencePath] = {}
    for path in paths:
        key = tuple((ref.source.value, ref.post_id or "", ref.web_fact_id or "") for ref in path.evidence)
        unique_paths[key] = path
    paths = list(unique_paths.values())
    return ProfileItem(
        attribute=ProfileAttribute.EMPLOYER_NAME,
        value=value,
        confidence=0.65,
        status=ProfileStatus.WEAK,
        evidence=[ref for path in paths for ref in path.evidence],
        evidence_paths=paths,
        assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY_PUBLIC_WEB),
    )


def infer_owner_claims_with_web(
    posts: list[Post], clues: list[Clue], web_facts: list[WebFact],
    owner_profile_text: str = "", self_report_clues: list[Clue] | None = None,
) -> list[ProfileItem]:
    """Combine direct and Web-backed paths; reject conflicting employer names."""
    claims = infer_owner_claims(posts, clues, owner_profile_text, self_report_clues)
    web_claim = infer_web_employer_claim(posts, web_facts, owner_profile_text)
    if web_claim is None:
        return claims
    direct = next((item for item in claims if item.attribute is ProfileAttribute.EMPLOYER_NAME), None)
    if direct is None:
        return [*claims, web_claim]
    if _normalize_bridge(direct.value or "") != _normalize_bridge(web_claim.value or ""):
        return [item for item in claims if item.attribute is not ProfileAttribute.EMPLOYER_NAME]
    paths = [*direct.evidence_paths, *web_claim.evidence_paths]
    merged = direct.model_copy(update={
        "evidence_paths": paths,
        "evidence": [ref for path in paths for ref in path.evidence],
        "assessment": direct.assessment.model_copy(update={"minimal_scope": _minimal_scope(paths)}),
    })
    return [merged if item is direct else item for item in claims]


def _forbidden_context(context: str) -> bool:
    value = context.casefold()
    return any(token in value for token in (
        "visitor", "logo-only", "visit-only", "guest", "訪問", "見学", "遊びに", "客として",
        "来場", "参加者として", "取引先", "委託", "外注", "派遣先",
    ))


def infer_owner_claims(
    posts: list[Post],
    clues: list[Clue],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
) -> list[ProfileItem]:
    """Parse narrow explicit Japanese bridges; ambiguous or unsupported text yields no claim.

    Residential pattern: an owner post names ``自宅近くのX`` and a different post says
    ``XはY``. Employer pattern: an owner post says ``うちの会社のX`` and a different
    post says ``YのX``. Image-only logos, station signs, and visit statements are not inputs.
    """
    facts: list[CrossPostFact] = []
    self_report_clues = self_report_clues or []
    confidence = 0.65  # conservative provisional rule confidence; never presented as calibrated
    anchors = [(post.post_id, post.text, "post_text") for post in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    for anchor_post_id, anchor_text, anchor_source in anchors:
        if _forbidden_context(anchor_text):
            continue
        for attribute, anchor_pattern, value_pattern, clue_type, validator in (
            (ProfileAttribute.RESIDENTIAL_AREA, r"自宅近くの(?P<bridge>[^\s、。]+)", r"{bridge}(?:は|が)(?P<value>[^\s、。]+)", ClueType.PLACE_TEXT, _is_residential_value),
            (ProfileAttribute.EMPLOYER_NAME, r"うちの会社の(?P<bridge>[^\s、。]+)", r"(?P<value>[^\s、。]+?)の{bridge}", ClueType.ORG_TEXT, _is_organization_name),
        ):
            anchor_match = re.search(anchor_pattern, anchor_text)
            if not anchor_match:
                continue
            bridge_text = anchor_match.group("bridge").rstrip("ですだにへをがは")
            bridge = _normalize_bridge(bridge_text)
            if not _is_distinctive_bridge(bridge_text):
                continue
            bridge_id = f"home:{bridge}" if attribute is ProfileAttribute.RESIDENTIAL_AREA else f"employer:{bridge}"
            facts.append(CrossPostFact(anchor_post_id, None, FactRole.OWNER_RELATION, bridge_text, confidence,
                                       bridge_id, True, excerpt=anchor_match.group(0), source=anchor_source))

            for supporting_post in posts:
                if _forbidden_context(supporting_post.text):
                    continue
                if supporting_post.post_id != anchor_post_id and bridge_text in supporting_post.text:
                    facts.append(CrossPostFact(supporting_post.post_id, None, FactRole.BRIDGE, bridge_text,
                                               confidence, bridge_id, excerpt=bridge_text))
                if supporting_post.post_id == anchor_post_id:
                    continue
                match = re.search(value_pattern.format(bridge=re.escape(bridge_text)), supporting_post.text)
                if not match:
                    continue
                value = match.group("value").rstrip("ですだにへをがは")
                if not value or not validator(value):
                    continue
                typed = _matching_text_clue(clues, supporting_post.post_id, value, clue_type)
                if typed is None:
                    continue
                clue_index, clue = typed
                facts.append(CrossPostFact(
                    supporting_post.post_id, clue_index, FactRole.SPECIFIC_VALUE, value, clue.confidence,
                    bridge_id, excerpt=match.group(0),
                    related_evidence=(ProfileEvidence(post_id=supporting_post.post_id, clue_index=None,
                        required=True, source="post_text", excerpt=match.group(0)),),
                ))

            if owner_profile_text.strip():
                match = re.search(value_pattern.format(bridge=re.escape(bridge_text)), owner_profile_text)
                if match:
                    value = match.group("value").rstrip("ですだにへをがは")
                    typed = _matching_profile_clue(self_report_clues, value, clue_type)
                    if value and validator(value) and typed:
                        facts.append(CrossPostFact(None, None, FactRole.SPECIFIC_VALUE, value, typed.confidence,
                            bridge_id, excerpt=match.group(0), source="profile_text"))

    return [
        item for attribute in (ProfileAttribute.RESIDENTIAL_AREA, ProfileAttribute.EMPLOYER_NAME)
        if (item := infer_cross_post_claim(attribute, facts)) is not None
    ]


def _normalize_bridge(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _is_distinctive_bridge(value: str) -> bool:
    """Require a named bridge, rejecting generic nouns such as 研修 or 商店街."""
    bridge = _normalize_bridge(value)
    generic_suffixes = (
        "商店街", "ショッピングモール", "モール", "研修", "研修会", "駅", "商店", "店",
        "会社", "ビル", "オフィス", "病院", "学校", "公園", "通り", "施設",
    )
    for suffix in generic_suffixes:
        if bridge.endswith(suffix):
            name = bridge[: -len(suffix)]
            return len(name) >= 2 and any(ch.isalnum() or "\u3040" <= ch <= "\u9fff" for ch in name)
    return len(bridge) >= 3 and any(ch.isalpha() for ch in bridge)


def _matching_text_clue(clues: list[Clue], post_id: str, value: str, clue_type: ClueType) -> tuple[int, Clue] | None:
    for index, clue in enumerate(clues):
        if (clue.post_id == post_id and clue.source is ClueSource.TEXT and clue.type is clue_type
                and _normalize_bridge(clue.value) == _normalize_bridge(value)):
            return index, clue
    return None


def _matching_profile_clue(clues: list[Clue], value: str, clue_type: ClueType) -> Clue | None:
    return next((clue for clue in clues if clue.source is ClueSource.PROFILE_TEXT and clue.type is clue_type
                 and _normalize_bridge(clue.value) == _normalize_bridge(value)), None)


def _is_residential_value(value: str) -> bool:
    return value.endswith(("市", "区", "町", "村", "郡", "丁目", "団地", "エリア"))


def _is_organization_name(value: str) -> bool:
    normalized = value.strip()
    legal_prefixes = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社")
    if any(normalized.startswith(prefix) and len(normalized.removeprefix(prefix)) >= 2 for prefix in legal_prefixes):
        return True
    return normalized.endswith(("社", "株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "商事", "銀行", "大学", "法人"))
