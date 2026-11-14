from dataclasses import replace

import numpy as np
import pytest

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine.gazetteer import CollectionArea
from tkb_engine.scoring.constants import COVERAGE
from tkb_engine.scoring.estimate import (
    age_label,
    coverage_cells,
    describe_cell,
    estimate,
    rank_percent,
)
from tkb_engine.scoring.tables import ScoringTables, Shelter

AREAS = [CollectionArea("文京区", "弥生1・2丁目", "月木", ["弥生1・2丁目"])]


def post(n: int, text: str, images: int = 0) -> Post:
    return Post.model_validate(
        {
            "post_id": f"at://did:plc:x/app.bsky.feed.post/{n}",
            "text": text,
            "created_at": f"2026-11-{n:02d}T21:00:00+09:00",
            "images": [
                {
                    "index": 0,
                    "url": f"https://cdn.bsky.app/img/feed_fullsize/plain/x/{n}",
                    "alt": "",
                    "width": 10,
                    "height": 10,
                }
            ]
            * images,
        }
    )


def photo(n: int, source: ClueSource) -> Clue:
    return Clue(
        post_id=f"at://did:plc:x/app.bsky.feed.post/{n}",
        image_index=0,
        type=ClueType.ADDRESS_TEXT,
        value="弥生",
        region=None,
        confidence=0.9,
        source=source,
    )


POSTS = [
    post(1, "千代田線、また止まってる…"),
    post(2, "近所の猫、今日もいた", images=1),
    post(3, "燃えるゴミ、月木なのにまた出し忘れた"),
    post(4, "22歳、いまだに自炊がうまくならない"),
    post(5, "誕生日が4月14日だと、毎年誰にも祝われない"),
    post(6, "今日は一日なにもしなかった"),
]
CLUES = [photo(2, ClueSource.OCR), photo(2, ClueSource.VLM)]


def test_estimate_returns_none_without_location_signals(tables: ScoringTables) -> None:
    assert estimate([POSTS[3], POSTS[5]], [], tables, AREAS) is None


def test_estimate_combines_layers_and_narrows_step_by_step(tables: ScoringTables) -> None:
    result = estimate(POSTS, CLUES, tables, AREAS)

    assert result is not None
    assert result.probability.sum() == pytest.approx(1.0)
    assert result.age == 22 and result.birthday == "4月14日"
    # 投稿なし → 千代田線 → 弥生 → 月木 → 22歳 → 誕生日
    assert [pid[-1] if pid else None for pid, _ in result.steps] == [None, "1", "2", "3", "4", "5"]
    people = [region.people for _, region in result.steps]
    assert people[0] == pytest.approx(COVERAGE * 1000, rel=0.05)  # 総人口 1,000 人の 8割ほど
    assert people[-2] < people[0]
    # 層8：8割の範囲の 20〜24歳 ÷ 5 ÷ 365
    last = result.steps[-1][1]
    assert last.same_birthday == pytest.approx(last.people / 5 / 365)
    assert result.steps[-2][1].same_birthday is None
    # 中野区の弥生町（月木のデータがない区）も 弥生 には当てはまる
    assert set(tables.town[coverage_cells(result.probability)].tolist()) <= {0, 2}


def test_estimate_reports_what_each_post_contributes(tables: ScoringTables) -> None:
    result = estimate(POSTS, CLUES, tables, AREAS)

    assert result is not None
    assert "at://did:plc:x/app.bsky.feed.post/6" not in result.without
    photo_post = "at://did:plc:x/app.bsky.feed.post/2"
    assert result.without[photo_post].people > result.region.people
    used = {(e.signal.layer, e.signal.value, e.applied) for e in result.evidence}
    assert (5, "弥生", True) in used and (2, "千代田線", True) in used
    assert (8, "4月14日", True) in used


def test_estimate_marks_signals_that_cannot_be_used(tables: ScoringTables) -> None:
    result = estimate([post(1, "山手線、また止まってる…")], [], tables, AREAS)
    assert result is None or all(not e.applied for e in result.evidence)
    unknown = estimate([post(1, "近所のひみつ基地が避難所")], [], tables, AREAS)
    assert unknown is not None
    assert [e.applied for e in unknown.evidence] == [False]


def test_estimate_returns_both_with_and_without_the_geoprofile(tables: ScoringTables) -> None:
    shelters = [
        Shelter("東京大学", float(tables.lat[0]), float(tables.lon[0])),
        Shelter("上野公園", float(tables.lat[99]), float(tables.lon[99])),
    ]
    world = replace(tables, shelters=shelters)
    posts = [
        *POSTS[:2],
        post(7, "東大の構内、散歩コースにちょうどいい"),
        post(8, "上野公園によく行く"),
    ]

    result = estimate(posts, CLUES, world, AREAS)

    assert result is not None and result.geoprofile is not None
    assert [p.name for p in result.geoprofile.places] == ["東京大学", "上野公園"]
    assert result.with_geoprofile is not None
    with_geo, _ = result.with_geoprofile
    assert with_geo.sum() == pytest.approx(1.0)
    assert not np.allclose(with_geo, result.probability)


def test_coverage_cells_reaches_the_coverage() -> None:
    probability = np.array([0.5, 0.05, 0.3, 0.15])
    assert coverage_cells(probability).tolist() == [0, 2]
    assert coverage_cells(np.array([0.25] * 4)).tolist() == [0, 1, 2, 3]


def test_rank_percent_counts_cells_with_higher_probability() -> None:
    assert rank_percent(np.array([0.1, 0.4, 0.4, 0.1]), 3) == (3, 75.0)
    assert rank_percent(np.array([0.1, 0.4, 0.4, 0.1]), 2) == (1, 25.0)


def test_describe_cell_and_age_label(tables: ScoringTables) -> None:
    described = describe_cell(tables, 0)
    assert described["city"] == "文京区" and described["town"] == "弥生二丁目"
    assert described["station"] == "東大前"
    assert isinstance(described["station_walk_minutes"], int)
    outside = replace(tables, town=np.full(tables.size, -1, dtype=np.int32))
    assert describe_cell(outside, 0)["town"] is None
    assert age_label(22) == "20〜24歳" and age_label(None) is None
