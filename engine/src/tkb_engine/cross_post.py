"""Conservative claim paths for residential area, commute station, and employer evidence."""

import re
import unicodedata
from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta, timezone
from itertools import combinations

from tkb_common.schemas import (
    ClaimAssessment,
    Clue,
    ClueSource,
    ClueType,
    EvidenceScope,
    Post,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
    WebFact,
    WebSourceKind,
    WebVerificationStatus,
)
from tkb_engine.child_school import BRIDGE_PREFIX as CHILD_SCHOOL_BRIDGE
from tkb_engine.child_school import child_school_facts
from tkb_engine.cross_post_facts import CrossPostFact, FactRole
from tkb_engine.cross_post_facts import forbidden_context as _forbidden_context
from tkb_engine.cross_post_facts import is_distinctive_bridge as _is_distinctive_bridge
from tkb_engine.cross_post_facts import matching_text_clue as _matching_text_clue
from tkb_engine.cross_post_facts import normalize_bridge as _normalize_bridge
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.open_data import infer_registry_employer_claim, shelter_home_facts
from tkb_engine.open_data_bus import bus_stop_home_facts
from tkb_engine.open_data_school import add_school_district_residence

__all__ = ["CrossPostFact", "FactRole"]


def infer_cross_post_claim(
    attribute: ProfileAttribute,
    facts: list[CrossPostFact],
) -> ProfileItem | None:
    """Build only unambiguous AND paths spanning at least two independent posts.

    Each successful path needs one explicit owner-relation fact and one value fact, in
    different posts, joined by the same explicit bridge. Any competing value invalidates the
    claim instead of choosing one. Confidence is the weakest fact on the AND path.
    """
    if attribute not in CROSS_POST_BRIDGES:
        raise ValueError(
            "cross-post gate is only defined for residential_area, regular_station and child_school"
        )
    expected_bridge = {
        ProfileAttribute.RESIDENTIAL_AREA: "home:",
        ProfileAttribute.REGULAR_STATION: "regular_station:",
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
            key = value_fact.value.strip().casefold()
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


CROSS_POST_BRIDGES = {
    ProfileAttribute.RESIDENTIAL_AREA,
    ProfileAttribute.REGULAR_STATION,
    ProfileAttribute.CHILD_SCHOOL,
}


def infer_child_school_claim(
    posts: list[Post], clues: list[Clue], gazetteer: Gazetteer
) -> ProfileItem | None:
    """子どもの学校。本人との関係と学校名が別々の投稿にあり、同じ橋渡しでつながるときだけ。"""
    claim = infer_cross_post_claim(
        ProfileAttribute.CHILD_SCHOOL, child_school_facts(posts, clues, gazetteer)
    )
    if claim is None:
        return None
    return claim.model_copy(
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
    return item.model_copy(
        update={
            "evidence_paths": surviving,
            "evidence": [e for path in surviving for e in path.evidence],
            "confidence": confidence,
            "status": ProfileStatus.FOUND if confidence >= 0.8 else ProfileStatus.WEAK,
            "assessment": item.assessment.model_copy(
                update={"minimal_scope": _minimal_scope(surviving)}
            ),
        }
    )


def claims_after_deletion(
    claims: Sequence[ProfileItem], deleted_post_ids: Collection[str]
) -> list[ProfileItem]:
    """消した投稿を根拠から除いたプロフィール推定。根拠がなくなった推定は返さない。

    画面の profileClaimsAfterDeletion（web/src/types/profile.ts）と同じ規則にする。
    根拠の経路（evidence_paths）があれば recalculate_after_deletion で計算し直す。経路のない推定と
    unknown は計算し直せないので、消した投稿を根拠に含むものだけを除く。
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
                            ProfileEvidencePath(evidence=evidence, confidence=0.65)
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
        status=ProfileStatus.WEAK,
        evidence=[ref for path in paths for ref in path.evidence],
        evidence_paths=paths,
        assessment=ClaimAssessment(minimal_scope=EvidenceScope.BLUESKY_PUBLIC_WEB),
    )


def infer_owner_claims_with_web(
    posts: list[Post],
    clues: list[Clue],
    web_facts: list[WebFact],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
    gazetteer: Gazetteer | None = None,
    *,
    diagnosis_date: date | None = None,
) -> list[ProfileItem]:
    """Combine direct and Web-backed paths; reject conflicting employer names."""
    claims = infer_owner_claims(
        posts,
        clues,
        owner_profile_text,
        self_report_clues,
        gazetteer,
        diagnosis_date=diagnosis_date,
    )
    # 手元の法人番号の表で確かめられたときは、そちらを使う（公開Webの WebFact の経路の代わり）
    registry_claim = (
        infer_registry_employer_claim(posts, owner_profile_text, gazetteer)
        if gazetteer is not None
        else None
    )
    web_claim = registry_claim or infer_web_employer_claim(posts, web_facts, owner_profile_text)
    if web_claim is None:
        return claims
    direct = next(
        (item for item in claims if item.attribute is ProfileAttribute.EMPLOYER_NAME), None
    )
    if direct is None:
        return [*claims, web_claim]
    if _normalize_bridge(direct.value or "") != _normalize_bridge(web_claim.value or ""):
        return [item for item in claims if item.attribute is not ProfileAttribute.EMPLOYER_NAME]
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
    return [merged if item is direct else item for item in claims]


def infer_owner_claims(
    posts: list[Post],
    clues: list[Clue],
    owner_profile_text: str = "",
    self_report_clues: list[Clue] | None = None,
    gazetteer: Gazetteer | None = None,
    *,
    diagnosis_date: date | None = None,
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

    if gazetteer is not None:
        facts.extend(shelter_home_facts(posts, clues, owner_profile_text, gazetteer))
        facts.extend(bus_stop_home_facts(posts, clues, owner_profile_text, gazetteer))
    claims = [
        item
        for item in [infer_cross_post_claim(ProfileAttribute.RESIDENTIAL_AREA, facts)]
        if item is not None
    ]
    child_age = infer_child_age_claim(posts, diagnosis_date=diagnosis_date)
    if child_age is not None:
        claims.append(child_age)
    if gazetteer is not None:
        regular_station = infer_regular_station_claim(posts, clues, gazetteer)
        if regular_station is not None:
            claims.append(regular_station)
        child_school = infer_child_school_claim(posts, clues, gazetteer)
        if child_school is not None:
            claims.append(child_school)
        # 子どもの学校の推定があれば、その学区の区市町村を居住地域の経路に足す
        claims = add_school_district_residence(claims, gazetteer)
    return claims


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


def infer_child_age_claim(
    posts: list[Post], diagnosis_date: date | None = None
) -> ProfileItem | None:
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

    # Reject any ambiguity, including multiple eligible children or competing
    # birth-year/birthday posts. Do not silently select one pair.
    if len(candidates) != 1:
        return None
    age, birth_post, birth_excerpt, birthday_post, birthday_excerpt = candidates[0]
    confidence = 0.55  # provisional rule strength; not a calibrated probability
    path = ProfileEvidencePath(
        evidence=[
            ProfileEvidence(
                post_id=birth_post.post_id, required=True, source="post_text", excerpt=birth_excerpt
            ),
            ProfileEvidence(
                post_id=birthday_post.post_id,
                required=True,
                source="post_text",
                excerpt=birthday_excerpt,
            ),
        ],
        confidence=confidence,
    )
    return ProfileItem(
        attribute=ProfileAttribute.CHILD_AGE,
        value=f"{age}歳",
        confidence=confidence,
        status=ProfileStatus.WEAK,
        evidence=path.evidence,
        evidence_paths=[path],
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
    return any(mark in text for mark in ("「", "『", "“", "”", "『", "引用"))


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


def infer_regular_station_claim(
    posts: list[Post],
    clues: list[Clue],
    gazetteer: Gazetteer,
) -> ProfileItem | None:
    """Infer a commute station only from a habit post plus a linked OCR sign post."""
    known_names = {
        unicodedata.normalize("NFKC", row["station_name"]).strip()
        for row in gazetteer.stations
        if isinstance(row.get("station_name"), str) and row["station_name"].strip()
    }
    if not known_names:
        return None

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
        if any("x" in clue.value.casefold() for clue in post_station_clues):
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
            and "x" not in clue.value.casefold()
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

    claim = infer_cross_post_claim(ProfileAttribute.REGULAR_STATION, facts)
    if claim is None:
        return None
    return claim.model_copy(update={"value": f"{claim.value}駅"})


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
