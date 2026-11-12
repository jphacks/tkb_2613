"""子どもの学校（child_school）の推定と、学区からの居住地域の経路。

学校名・地名はすべて架空（実在の子どもや学校を思わせる値は使わない）。
"""

from datetime import datetime

import pytest

from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    Post,
    ProfileAttribute,
    ProfileItem,
)
from tkb_engine.cross_post import (
    infer_owner_claims,
    plan_profile_claim_deletion,
    recalculate_after_deletion,
)
from tkb_engine.gazetteer import Gazetteer


def post(key: str, text: str) -> Post:
    return Post(
        post_id=f"at://did:plc:owner/app.bsky.feed.post/{key}",
        text=text,
        created_at=datetime.fromisoformat("2026-10-20T08:31:00+09:00"),
        images=[],
    )


def org(p: Post, value: str) -> Clue:
    return Clue(
        post_id=p.post_id,
        image_index=None,
        type=ClueType.ORG_TEXT,
        value=value,
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )


def district(name: str, city: str, kind: str = "小学校") -> dict[str, object]:
    return {"kind": kind, "name": name, "city": city, "terms": "オープンデータ公開", "note": ""}


GAZ = Gazetteer(
    school_districts=[
        district("かくれんぼ小学校", "架空区"),
        district("かくれんぼ小学校", "架空区"),  # 1つの学校の学区が2つに分かれた行
        district("おにごっこ中学校", "架空区", "中学校"),
        district("だるまさん小学校", "空想市"),
        district("ふたご小学校", "架空区"),
        district("ふたご小学校", "空想市"),
    ]
)

RELATION = post("a", "娘の小学校のひまわり祭りで踊った")
VALUE = post("b", "ひまわり祭りはかくれんぼ小学校の行事らしい")
VALUE_CLUE = org(VALUE, "かくれんぼ小学校")


def of(claims: list[ProfileItem], attribute: ProfileAttribute) -> ProfileItem | None:
    return next((c for c in claims if c.attribute is attribute), None)


def school(posts: list[Post], clues: list[Clue], gaz: Gazetteer = GAZ) -> ProfileItem | None:
    return of(infer_owner_claims(posts, clues, gazetteer=gaz), ProfileAttribute.CHILD_SCHOOL)


def test_relation_and_school_name_in_two_posts_infer_the_child_school() -> None:
    claims = infer_owner_claims([RELATION, VALUE], [VALUE_CLUE], gazetteer=GAZ)

    found = of(claims, ProfileAttribute.CHILD_SCHOOL)
    assert found is not None
    assert found.value == "かくれんぼ小学校"
    assert {e.post_id for e in found.evidence if e.post_id} == {RELATION.post_id, VALUE.post_id}
    assert found.assessment.harm_status == "prerequisites_unmet"
    # 学区の区市町村が居住地域の経路になる（#172）
    home = of(claims, ProfileAttribute.RESIDENTIAL_AREA)
    assert home is not None
    assert home.value == "架空区"
    assert any(e.source == "open_data" for e in home.evidence)


def test_short_school_name_resolves_to_the_table_name() -> None:
    value = post("b", "ひまわり祭りってかくれんぼ小のだよね")
    found = school([RELATION, value], [org(value, "かくれんぼ小")])
    assert found is not None
    assert found.value == "かくれんぼ小学校"


@pytest.mark.parametrize(
    "relation",
    [
        "うちの子の学校のひまわり祭り、今年も雨",
        "うちの息子が通う中学校のひまわり祭りに行った",
        "私の娘の学校のひまわり祭りの準備",
        "長男の通う小学校のひまわり祭り",
    ],
)
def test_owner_relations(relation: str) -> None:
    assert school([post("a", relation), VALUE], [VALUE_CLUE]) is not None


@pytest.mark.parametrize(
    ("relation", "value"),
    [
        ("友達の娘の小学校のひまわり祭りに招かれた", VALUE.text),
        ("姉の息子の学校のひまわり祭り", VALUE.text),
        ("娘の受験する小学校のひまわり祭り", VALUE.text),
        ("娘の小学校のひまわり祭りを見学", VALUE.text),
        ("ひまわり祭り楽しかった", VALUE.text),  # 本人の子どもとのつながりがない
        # 一般の行事名は、どの学校にもあるので橋渡しにしない
        ("娘の小学校の運動会", "運動会はかくれんぼ小学校の行事"),
        ("娘の小学校の夏祭り", "夏祭りはかくれんぼ小学校の行事"),
    ],
)
def test_no_inference_without_an_explicit_owner_child_relation(relation: str, value: str) -> None:
    value_post = post("b", value)
    assert school([post("a", relation), value_post], [org(value_post, "かくれんぼ小学校")]) is None


def test_relation_and_school_in_one_post_is_not_enough() -> None:
    one = post("a", "娘の小学校のひまわり祭り。ひまわり祭りはかくれんぼ小学校の行事")
    assert school([one], [org(one, "かくれんぼ小学校")]) is None


def test_school_name_needs_the_text_clue() -> None:
    assert school([RELATION, VALUE], []) is None


def test_photo_clues_alone_do_not_infer() -> None:
    photo = post("c", "")
    uniform = Clue(
        post_id=photo.post_id,
        image_index=0,
        type=ClueType.UNIFORM,
        value="かくれんぼ小学校の制服",
        region=None,
        confidence=0.95,
        source=ClueSource.VLM,
    )
    assert school([RELATION, photo], [uniform]) is None


def test_same_school_name_in_two_cities_is_not_inferred() -> None:
    value = post("b", "ひまわり祭りはふたご小学校の行事")
    assert school([RELATION, value], [org(value, "ふたご小学校")]) is None


def test_school_not_in_the_table_or_no_table_is_not_inferred() -> None:
    value = post("b", "ひまわり祭りはまぼろし小学校の行事")
    assert school([RELATION, value], [org(value, "まぼろし小学校")]) is None
    assert school([RELATION, VALUE], [VALUE_CLUE], Gazetteer()) is None


def test_two_schools_for_the_same_bridge_are_dropped() -> None:
    other = post("c", "ひまわり祭りはだるまさん小学校のだよ")
    clues = [VALUE_CLUE, org(other, "だるまさん小学校")]
    assert school([RELATION, VALUE, other], clues) is None


def test_deleting_the_relation_or_school_post_breaks_both_paths() -> None:
    claims = infer_owner_claims([RELATION, VALUE], [VALUE_CLUE], gazetteer=GAZ)
    found = of(claims, ProfileAttribute.CHILD_SCHOOL)
    home = of(claims, ProfileAttribute.RESIDENTIAL_AREA)
    assert found is not None
    assert home is not None

    for deleted in (RELATION.post_id, VALUE.post_id):
        assert recalculate_after_deletion(found, {deleted}) is None
        assert recalculate_after_deletion(home, {deleted}) is None
    assert plan_profile_claim_deletion(claims, [RELATION, VALUE])
