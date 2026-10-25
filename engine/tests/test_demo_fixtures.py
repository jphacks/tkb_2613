"""eval/fixtures のデモ用アカウントで、推理と削除の提案が expected どおりになるか。

data-prep の表（make data）はテストでは使えないので、fixture に要る駅と郵便番号だけの表を
組み立てる。
知識表は data-prep/manual/knowledge.json をそのまま読む。
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tkb_common.schemas import Clue, Post
from tkb_engine import Gazetteer, infer, plan
from tkb_engine.gazetteer import Knowledge

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"

GAZ = Gazetteer(
    stations=[
        {"station_name": "根津", "mesh_1km": "m-bunkyo"},
        {"station_name": "根岸", "mesh_1km": "m-taito"},
        {"station_name": "八王子", "mesh_1km": "m-hachioji", "lat": 35.6558, "lon": 139.3389},
        {"station_name": "京王八王子", "mesh_1km": "m-hachioji", "lat": 35.6575, "lon": 139.3437},
        {"station_name": "三鷹", "mesh_1km": "m-mitaka", "lat": 35.7027, "lon": 139.5607},
        {"station_name": "吉祥寺", "mesh_1km": "m-musashino", "lat": 35.7031, "lon": 139.5797},
        {"station_name": "王子", "mesh_1km": "m-kita"},
        # 多摩地域の駅（高尾は demo_tkb2613.json の「高尾山が近い」）
        {"station_name": "聖蹟桜ヶ丘", "mesh_1km": "m-tama", "lat": 35.6508, "lon": 139.4469},
        {"station_name": "永山", "mesh_1km": "m-tama", "lat": 35.6302, "lon": 139.4479},
        {"station_name": "多摩センター", "mesh_1km": "m-tama", "lat": 35.6250, "lon": 139.4243},
        {"station_name": "唐木田", "mesh_1km": "m-tama", "lat": 35.6167, "lon": 139.4106},
        {"station_name": "田無", "mesh_1km": "m-nishitokyo", "lat": 35.7272, "lon": 139.5394},
        {"station_name": "ひばりヶ丘", "mesh_1km": "m-nishitokyo", "lat": 35.7516, "lon": 139.5461},
        {"station_name": "昭島", "mesh_1km": "m-akishima", "lat": 35.7056, "lon": 139.3529},
        {"station_name": "福生", "mesh_1km": "m-fussa", "lat": 35.7385, "lon": 139.3270},
        {"station_name": "羽村", "mesh_1km": "m-hamura", "lat": 35.7578, "lon": 139.3155},
        {"station_name": "秋川", "mesh_1km": "m-akiruno", "lat": 35.7275, "lon": 139.2850},
        {"station_name": "青梅", "mesh_1km": "m-ome", "lat": 35.7905, "lon": 139.2583},
        {"station_name": "町田", "mesh_1km": "m-machida", "lat": 35.5422, "lon": 139.4455},
        {"station_name": "高尾", "mesh_1km": "m-hachioji", "lat": 35.6420, "lon": 139.2826},
        {"station_name": "運河", "mesh_1km": "m-nagareyama", "lat": 35.9145, "lon": 139.9067},
        {"station_name": "高尾山口", "mesh_1km": "m-hachioji", "lat": 35.6324, "lon": 139.2700},
    ],
    postal=[
        {"postal_code": "1130032", "muni_code": "13105", "city": "文京区", "town": "弥生"},
        {"postal_code": "1920083", "muni_code": "13201", "city": "八王子市", "town": "旭町"},
        {"postal_code": "1920082", "muni_code": "13201", "city": "八王子市", "town": "東町"},
        {"postal_code": "1140002", "muni_code": "13117", "city": "北区", "town": "王子"},
        {"postal_code": "1810013", "muni_code": "13204", "city": "三鷹市", "town": "下連雀"},
        {"postal_code": "1800004", "muni_code": "13203", "city": "武蔵野市", "town": "吉祥寺本町"},
        {"postal_code": "2060011", "muni_code": "13224", "city": "多摩市", "town": "関戸"},
        {"postal_code": "2020005", "muni_code": "13229", "city": "西東京市", "town": "住吉町"},
        {"postal_code": "1960015", "muni_code": "13207", "city": "昭島市", "town": "昭和町"},
        {"postal_code": "1970022", "muni_code": "13218", "city": "福生市", "town": "本町"},
        {"postal_code": "2050003", "muni_code": "13227", "city": "羽村市", "town": "緑ヶ丘"},
        {"postal_code": "1970804", "muni_code": "13228", "city": "あきる野市", "town": "秋川"},
        {"postal_code": "1980042", "muni_code": "13205", "city": "青梅市", "town": "東青梅"},
        {"postal_code": "1940013", "muni_code": "13209", "city": "町田市", "town": "原町田"},
    ],
    muni_meshes={
        "13105": {"m-bunkyo"},
        "13201": {"m-hachioji"},
        "13117": {"m-kita"},
        "13204": {"m-mitaka"},
        "13203": {"m-musashino"},
        "13224": {"m-tama"},
        "13229": {"m-nishitokyo"},
        "13207": {"m-akishima"},
        "13218": {"m-fussa"},
        "13227": {"m-hamura"},
        "13228": {"m-akiruno"},
        "13205": {"m-ome"},
        "13209": {"m-machida"},
    },
    knowledge=Knowledge.load(),
    schools=[
        {"name": "中央大学", "kind": "大学", "city": "八王子市"},
        {"name": "東京都立大学", "kind": "大学", "city": "八王子市"},
        {"name": "東京都立竹早高等学校", "kind": "高等学校", "city": "文京区"},
        {"name": "多摩大学", "kind": "大学", "city": "多摩市"},
        {"name": "東京医療学院大学", "kind": "大学", "city": "多摩市"},
    ],
)


def _load(name: str) -> tuple[list[Clue], list[Post], dict[str, Any]]:
    doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    clues = [Clue.model_validate(c) for c in doc["clues"]]
    posts = [Post.model_validate(p) for p in doc["posts"]]
    return clues, posts, doc


@pytest.mark.parametrize("name", ["demo_observations.json", "demo_aoi.json", "demo_tkb2613.json"])
def test_infer_gives_the_expected_values(name: str) -> None:
    clues, posts, doc = _load(name)

    got = {c.attribute: c for c in infer(clues, posts, GAZ)}

    for e in doc["expected"]:
        attribute = e["attribute"]
        assert attribute in got, attribute
        if attribute == "routine":
            assert "火曜" in got[attribute].value and "20時" in got[attribute].value
        else:
            assert got[attribute].value == e["value"]


def test_aoi_evidence_matches_the_expected_clues() -> None:
    clues, posts, doc = _load("demo_aoi.json")

    got = {c.attribute: c for c in infer(clues, posts, GAZ)}

    for e in doc["expected"]:
        assert got[e["attribute"]].clue_indices == sorted(e["clue_indices"]), e["attribute"]


def test_aoi_plan_deletes_the_trash_bag_and_the_mail() -> None:
    clues, posts, doc = _load("demo_aoi.json")

    proposal = plan(clues, posts, GAZ)

    assert set(proposal.delete) == set(doc["expected_plan"]["delete"])
    assert set(proposal.broken) == set(doc["expected_plan"]["broken"])
    # 残るのは名前と年齢だけで、住んでいる所はわからなくなる
    assert {c.attribute for c in proposal.after} == {"name", "age"}


def test_aoi_city_needs_both_the_trash_bag_and_the_distance_hint() -> None:
    clues, posts, _ = _load("demo_aoi.json")
    for clue_type in ("local_item", "place_text"):
        gone = next(c.post_id for c in clues if c.type.value == clue_type)
        kept = [c for c in clues if c.post_id != gone]

        got = {c.attribute for c in infer(kept, posts, GAZ)}

        # どちらか片方だけでは八王子市に決まらず、市で絞る駅・収集地区・学校も出ない
        assert not {"home_city", "home_district", "station", "school"} & got, clue_type


def test_tkb2613_evidence_and_plan() -> None:
    clues, posts, doc = _load("demo_tkb2613.json")

    got = {c.attribute: c for c in infer(clues, posts, GAZ)}
    proposal = plan(clues, posts, GAZ)

    for e in doc["expected"]:
        assert got[e["attribute"]].clue_indices == sorted(e["clue_indices"]), e["attribute"]
    # 同じ日にまとめて投稿したので、時刻を使う推理は出ない
    assert not {"active_time", "routine"} & set(got)
    assert set(proposal.delete) == set(doc["expected_plan"]["delete"])
    assert set(proposal.broken) == set(doc["expected_plan"]["broken"])


def test_tkb2613_city_needs_the_trash_bag_and_the_kichijoji_hint() -> None:
    clues, posts, _ = _load("demo_tkb2613.json")
    needed = [c.post_id for c in clues if c.value == "吉祥寺" or c.type.value == "local_item"]
    for gone in needed:
        kept = [c for c in clues if c.post_id != gone]

        got = {c.attribute for c in infer(kept, posts, GAZ)}

        assert "home_city" not in got, gone
