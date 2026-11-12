"""居住地域の経路を重ねる架空デモ（eval/fixtures/demo_layered.json）で、実際に出る結論を固定する。

表は公開データ（data/processed）のうち、このデモが使う行だけを写したもの。知識表（収集地区）は
リポジトリの data-prep/manual/knowledge.json をそのまま読む。
ゴミの日（R5）は町（千駄木3～5丁目）まで出るが、避難所・バス停・学区の経路は表が区市町村までしか
持たないので、重なるのは区（文京区）まで。
"""

import json
from datetime import date
from pathlib import Path

from tkb_common.schemas import Clue, Post, ProfileAttribute, ProfileStatus
from tkb_engine.cross_post import infer_owner_claims, plan_profile_claim_deletion
from tkb_engine.gazetteer import Gazetteer, Knowledge
from tkb_engine.rules import infer

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_layered.json"
PREFIX = "at://did:plc:demolayered00000000000000/app.bsky.feed.post/"

GAZ = Gazetteer(
    postal=[
        {"postal_code": "1130022", "muni_code": "13105", "city": "文京区", "town": "千駄木"},
    ],
    knowledge=Knowledge.load(),
    shelters=[{"name": "千駄木小学校", "kind": "指定避難所", "city": "文京区"}],
    bus_stops=[{"name": "千駄木三丁目", "operator": "東京都", "cities": ["文京区"]}],
    school_districts=[
        {
            "kind": "小学校",
            "name": "林町小学校",
            "city": "文京区",
            "terms": "オープンデータ公開",
            "note": "",
        }
    ],
)


def _load() -> tuple[list[Post], list[Clue]]:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        [Post.model_validate(p) for p in doc["posts"]],
        [Clue.model_validate(c) for c in doc["clues"]],
    )


def test_garbage_day_and_address_narrow_to_one_collection_area() -> None:
    posts, clues = _load()

    found = {c.attribute: c for c in infer(clues, posts, GAZ)}

    assert found["home_district"].value == "文京区 千駄木3～5丁目"
    assert found["home_district"].clue_indices == [0, 1]


def test_shelter_bus_stop_and_school_district_all_point_to_the_same_ward() -> None:
    posts, clues = _load()

    claims = {
        c.attribute: c
        for c in infer_owner_claims(posts, clues, gazetteer=GAZ, diagnosis_date=date(2026, 11, 13))
    }

    school = claims[ProfileAttribute.CHILD_SCHOOL]
    assert school.value == "林町小学校"
    home = claims[ProfileAttribute.RESIDENTIAL_AREA]
    assert home.value == "文京区"
    # 3つの経路（避難所・バス停・学区）が同じ区で重なる。
    # 確からしさは経路の最大で、重ねても上がらない
    assert len(home.evidence_paths) == 3
    assert home.status is ProfileStatus.WEAK
    assert home.confidence == 0.65
    anchors = {
        e.post_id.removeprefix(PREFIX)
        for path in home.evidence_paths
        for e in path.evidence
        if e.post_id and e.source == "post_text"
    }
    assert anchors == {"l003", "l005", "l007"}


def test_three_anchor_posts_must_go_to_break_the_residential_area() -> None:
    posts, clues = _load()
    claims = infer_owner_claims(posts, clues, gazetteer=GAZ, diagnosis_date=date(2026, 11, 13))

    suggested = plan_profile_claim_deletion(claims, posts)

    assert [s.removeprefix(PREFIX) for s in suggested] == ["l003", "l005", "l007"]
