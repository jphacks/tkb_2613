"""法人番号の公表データ（手元の SQLite）で、本人が明示した勤務先の正式名称を確かめる経路。"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from tkb_common.corporate_name import normalize_corporate_name
from tkb_common.schemas import (
    EvidenceScope,
    Post,
    ProfileAttribute,
    ProfileItem,
    WebFact,
    WebSourceKind,
    WebVerificationStatus,
)
from tkb_engine.cross_post import infer_owner_claims_with_web, recalculate_after_deletion
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.open_data import infer_registry_employer_claim


def post(key: str, text: str) -> Post:
    return Post(
        post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}",
        text=text,
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )


def make_registry(path: Path, names: list[tuple[str, str]]) -> Path:
    with closing(sqlite3.connect(path)) as db:
        db.executescript(
            """
            CREATE TABLE corporations (corporate_number TEXT, name TEXT, normalized_name TEXT,
              furigana TEXT, pref_code TEXT);
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO meta VALUES ('as_of', '2026-10-30');
            """
        )
        db.executemany(
            "INSERT INTO corporations VALUES (?, ?, ?, '', '13')",
            [(number, name, normalize_corporate_name(name)) for number, name in names],
        )
        db.commit()
    return path


@pytest.fixture
def gaz(tmp_path: Path) -> Gazetteer:
    path = make_registry(
        tmp_path / "corporations.sqlite",
        [
            ("1000000000001", "株式会社青空商事"),
            ("1000000000002", "夕焼け工業株式会社"),
            ("1000000000003", "夕焼け工業合同会社"),
            ("1000000000004", "青空商事ホールディングス株式会社"),
        ],
    )
    return Gazetteer(corporations_path=path)


def test_gazetteer_looks_up_the_normalized_name_on_disk(gaz: Gazetteer) -> None:
    assert gaz.corporations_named("(株)青空商事") == [("1000000000001", "株式会社青空商事")]
    assert gaz.corporations_named("青空") == []
    assert gaz.corporations_as_of() == "2026-10-30"
    assert Gazetteer().corporations_named("青空商事") == []


def test_named_workplace_and_another_post_give_the_legal_name(gaz: Gazetteer) -> None:
    anchor = post("a", "今日も青空商事で働いてる。残業つらい")
    other = post("b", "青空商事の新しいビル、きれい")

    claim = infer_registry_employer_claim([anchor, other], "", gaz)

    assert claim is not None
    assert claim.attribute is ProfileAttribute.EMPLOYER_NAME
    assert claim.value == "株式会社青空商事"
    assert claim.assessment.minimal_scope is EvidenceScope.BLUESKY
    refs = claim.evidence_paths[0].evidence
    assert {r.post_id for r in refs if r.post_id} == {anchor.post_id, other.post_id}
    cited = [r for r in refs if r.source == "open_data"]
    assert len(cited) == 1
    assert "国税庁法人番号公表サイト" in (cited[0].excerpt or "")
    assert "2026年10月30日時点" in (cited[0].excerpt or "")
    # 法人番号は出さない
    assert "1000000000001" not in (cited[0].excerpt or "")


@pytest.mark.parametrize(
    "text",
    ["勤務先は青空商事です", "私の勤め先は青空商事", "青空商事に勤めています"],
)
def test_other_explicit_phrases(gaz: Gazetteer, text: str) -> None:
    claim = infer_registry_employer_claim([post("a", text), post("b", "青空商事の社食")], "", gaz)
    assert claim is not None
    assert claim.value == "株式会社青空商事"


def test_one_post_alone_gives_nothing(gaz: Gazetteer) -> None:
    assert infer_registry_employer_claim([post("a", "青空商事で働いてる")], "", gaz) is None


def test_two_corporations_with_the_same_name_give_nothing(gaz: Gazetteer) -> None:
    posts = [post("a", "夕焼け工業で働いてる"), post("b", "夕焼け工業の工場見えた")]
    assert infer_registry_employer_claim(posts, "", gaz) is None


def test_a_partial_name_is_not_expanded(gaz: Gazetteer) -> None:
    # 「青空」から「株式会社青空商事」を探さない
    posts = [post("a", "青空で働いてる"), post("b", "青空の話")]
    assert infer_registry_employer_claim(posts, "", gaz) is None


@pytest.mark.parametrize(
    "text",
    [
        "兄は青空商事で働いてる",
        "取引先の青空商事で働いてる人と会った",
        "青空商事を訪問。ここで働いてる人は楽しそう",
        "青空商事で働いてる人が多い街",
        "青空商事で働いている友達と飲んだ",
    ],
)
def test_third_parties_and_visits_are_not_the_owner(gaz: Gazetteer, text: str) -> None:
    posts = [post("a", text), post("b", "青空商事のビル")]
    assert infer_registry_employer_claim(posts, "", gaz) is None


def test_profile_anchor_needs_two_posts(gaz: Gazetteer) -> None:
    one = [post("a", "青空商事のビル")]
    two = [*one, post("b", "青空商事の社食")]
    assert infer_registry_employer_claim(one, "青空商事で働いています", gaz) is None
    claim = infer_registry_employer_claim(two, "青空商事で働いています", gaz)
    assert claim is not None
    assert any(r.source == "profile_text" for r in claim.evidence)


def test_deleting_a_post_breaks_the_claim(gaz: Gazetteer) -> None:
    anchor, other = post("a", "青空商事で働いてる"), post("b", "青空商事の社食")
    claim = infer_registry_employer_claim([anchor, other], "", gaz)
    assert claim is not None
    assert recalculate_after_deletion(claim, {other.post_id}) is None


def _web_fact(subject: str, legal: str) -> WebFact:
    return WebFact(
        id="mock-1",
        subject=subject,
        relation="legal_name_of",
        object=legal,
        source_url="https://example.com/company",
        source_title="架空の会社概要",
        source_kind=WebSourceKind.OFFICIAL_ORGANIZATION,
        excerpt="架空",
        retrieved_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        verification_status=WebVerificationStatus.VERIFIED,
    )


def employer(claims: list[ProfileItem]) -> ProfileItem | None:
    return next((c for c in claims if c.attribute is ProfileAttribute.EMPLOYER_NAME), None)


def test_registry_claim_replaces_the_mock_web_fact_only_when_confirmed(gaz: Gazetteer) -> None:
    posts = [post("a", "勤務先は青空商事です"), post("b", "青空商事の社食")]
    facts = [_web_fact("青空商事", "株式会社青空商事")]

    with_table = employer(infer_owner_claims_with_web(posts, [], facts, gazetteer=gaz))
    assert with_table is not None
    assert {r.source for r in with_table.evidence} >= {"open_data"}
    assert all(r.source != "public_web" for r in with_table.evidence)

    without_table = employer(infer_owner_claims_with_web(posts, [], facts, gazetteer=Gazetteer()))
    assert without_table is not None
    assert any(r.source == "public_web" for r in without_table.evidence)


def test_someone_elses_workplace_in_another_post_does_not_block_the_owner(gaz: Gazetteer) -> None:
    posts = [
        post("a", "今日も青空商事で働いてる"),
        post("b", "青空商事の社食"),
        post("c", "駅前で夕焼け工業株式会社で働いてる人とすれ違った"),
    ]
    claim = infer_registry_employer_claim(posts, "", gaz)
    assert claim is not None
    assert claim.value == "株式会社青空商事"
