import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx

from tkb_api.bluesky import Diagnosis, SessionStore
from tkb_api.pipeline import (
    MAX_IMAGE_BYTES,
    ImageFetchError,
    demo_extractions,
    diagnose_events,
    fetch_images,
    load_gazetteer,
)
from tkb_api.routes.diagnose import read_diagnosis
from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION
from tkb_common.schemas import (
    Clue,
    ClueSource,
    ClueType,
    PhotoPlaceCandidate,
    PhotoPlaceEvidence,
    PhotoPlaceGranularity,
    PhotoPlaceLookupStatus,
    PhotoPlaceRelation,
    PhotoPlaceResult,
    PhotoPlaceSource,
    PhotoPlaceStatus,
    PhotoPlaceType,
    Post,
    ProfileAttribute,
)
from tkb_detect.batch import PostExtraction
from tkb_engine.cross_post import (
    infer_owner_candidate_sets_with_web,
)
from tkb_engine.gazetteer import Gazetteer

FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"
CDN = "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:xxxx"


def _post(n_images: int, text: str = "本文") -> Post:
    return Post.model_validate(
        {
            "post_id": "at://did:plc:xxxx/app.bsky.feed.post/1",
            "text": text,
            "created_at": "2026-10-20T08:31:00+09:00",
            "images": [
                {"index": i, "url": f"{CDN}/{i}@jpeg", "alt": "", "width": 10, "height": 10}
                for i in range(n_images)
            ],
        }
    )


@pytest.mark.anyio
async def test_fetches_images_in_order_from_the_cdn() -> None:
    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").respond(content=b"first")
        router.get(f"{CDN}/1@jpeg").respond(content=b"second")

        assert await fetch_images(_post(2)) == [b"first", b"second"]


@pytest.mark.anyio
async def test_retries_temporary_cdn_failure() -> None:
    calls = 0

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, content=b"image")

    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").mock(side_effect=respond)

        assert await fetch_images(_post(1)) == [b"image"]
    assert calls == 2


@pytest.mark.anyio
async def test_refuses_hosts_other_than_the_cdn() -> None:
    # Post の検証を通り抜けた URL があっても、取りに行く前に止める
    post = _post(1)
    sneaky = post.images[0].model_copy(update={"url": "https://cdn.bsky.app.evil.test/a"})
    post = post.model_copy(update={"images": [sneaky]})

    with respx.mock(assert_all_called=False) as router, pytest.raises(ImageFetchError):
        await fetch_images(post)
    assert router.calls.call_count == 0


@pytest.mark.anyio
async def test_rejects_images_that_are_too_large() -> None:
    with respx.mock as router:
        router.get(f"{CDN}/0@jpeg").respond(content=b"x" * (MAX_IMAGE_BYTES + 1))

        with pytest.raises(ImageFetchError):
            await fetch_images(_post(1))


@pytest.mark.anyio
@pytest.mark.parametrize("reply", [httpx.Response(404), httpx.ConnectError("down")])
async def test_reports_download_failures_without_the_url(reply: Any) -> None:
    with respx.mock as router:
        route = router.get(f"{CDN}/0@jpeg")
        if isinstance(reply, Exception):
            route.mock(side_effect=reply)
        else:
            route.mock(return_value=reply)

        with pytest.raises(ImageFetchError) as excinfo:
            await fetch_images(_post(1))

    assert "cdn.bsky.app" not in str(excinfo.value)


def test_missing_tables_give_an_empty_gazetteer_with_the_knowledge(tmp_path: Path) -> None:
    gazetteer = load_gazetteer(tmp_path)

    assert gazetteer.stations == [] and gazetteer.postal == []
    # 知識表はリポジトリにあるので、data-prep の表がなくても読む
    assert gazetteer.knowledge.trash_bags


def test_demo_extractions_group_fixture_clues_by_post() -> None:
    import json

    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts = [Post.model_validate(p) for p in doc["posts"]]

    extractions = demo_extractions(FIXTURE, posts)

    assert [e.post_id for e in extractions] == [p.post_id for p in posts]
    assert sum(len(e.clues) for e in extractions) == len(doc["clues"])
    assert all(c.post_id == e.post_id for e in extractions for c in e.clues)


async def _stream(items: list[PostExtraction]) -> AsyncIterator[PostExtraction]:
    for item in items:
        yield item


@pytest.mark.anyio
async def test_events_keep_failed_posts_and_return_candidate_sets_only() -> None:
    post = _post(0, text="毎週火曜はジム")
    clue = Clue(
        post_id=post.post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value="毎週火曜はジム",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    extractions = [
        PostExtraction(post_id="at://other", clues=[], error="写真を取得できませんでした"),
        PostExtraction(post_id=post.post_id, clues=[clue]),
    ]

    saved_result: dict[str, Any] = {}
    events = [
        e
        async for e in diagnose_events(
            [post], _stream(extractions), Gazetteer(), on_result=saved_result.update
        )
    ]

    assert [name for name, _ in events] == ["post", "clues", "clues", "conclusions", "plan", "done"]
    assert events[1][1]["error"] == "写真を取得できませんでした"
    result = events[3][1]
    assert result["clues"] == [clue.model_dump(mode="json")]
    assert "conclusions" not in result
    assert len(result["profile_claims"]) == 29
    assert result["profile_relations"] == []
    claims_by_attr = {claim["attribute"]: claim for claim in result["profile_claims"]}
    assert claims_by_attr["routine"]["status"] == "candidate"
    assert claims_by_attr["routine"]["candidates"][0]["value"] == "毎週火曜（毎週火曜はジム）"
    assert all(
        claim["status"] == "unknown" and claim["candidates"] == []
        for attr, claim in claims_by_attr.items()
        if attr != "routine"
    )
    assert "home_room" not in claims_by_attr
    assert result["profile_claim_suggestions"] == [post.post_id]
    assert saved_result["clues"] == [clue]
    assert len(saved_result["profile_claims"]) == 29
    assert saved_result["profile_relations"] == []
    assert all(
        (claim.status == "candidate" if claim.attribute == "routine" else claim.status == "unknown")
        for claim in saved_result["profile_claims"]
    )


@pytest.mark.anyio
async def test_conclusions_event_returns_photo_unknown_without_changing_profile_candidates() -> (
    None
):
    post = _post(1)
    saved: dict[str, Any] = {}
    events = [
        event
        async for event in diagnose_events(
            [post],
            _stream([PostExtraction(post_id=post.post_id, clues=[])]),
            Gazetteer(),
            on_result=saved.update,
        )
    ]
    result = next(data for name, data in events if name == "conclusions")
    [photo_result] = result["photo_place_results"]
    assert photo_result["post_id"] == post.post_id
    assert photo_result["image_index"] == 0
    assert photo_result["status"] == "unknown"
    assert saved["photo_place_results"][0].status.value == "unknown"
    assert all(not claim.candidates for claim in saved["profile_claims"])


@pytest.mark.anyio
async def test_photo_place_candidate_does_not_become_a_profile_location_claim(
    tmp_path: Path,
) -> None:
    post = _post(1)
    clue = Clue(
        post_id=post.post_id,
        image_index=0,
        type=ClueType.SHOP,
        value="架空施設",
        region=(1, 1, 9, 9),
        confidence=0.95,
        source=ClueSource.OCR,
    )
    index = tmp_path / "places.sqlite3"
    record = {
        "place_id": "fixture:place",
        "label": "架空施設",
        "sources": [
            {
                "source_id": "fixture:record",
                "provider": "fixture",
                "dataset": "places",
                "license_id": "CC-BY-4.0",
                "record_id": "record",
                "version": "v1",
                "attribution": "fixture",
            }
        ],
    }
    with sqlite3.connect(index) as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.executescript(
            """
            CREATE TABLE poi_place (
                place_id TEXT PRIMARY KEY,
                license_verified INTEGER NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE poi_alias (
                name_key TEXT NOT NULL,
                place_id TEXT NOT NULL,
                PRIMARY KEY(name_key, place_id)
            );
            CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);
            """
        )
        db.execute(
            "INSERT INTO poi_place VALUES (?, 1, ?)",
            (record["place_id"], json.dumps(record, ensure_ascii=False)),
        )
        db.execute("INSERT INTO poi_alias VALUES (?, ?)", ("架空施設", record["place_id"]))
    saved: dict[str, Any] = {}

    events = [
        event
        async for event in diagnose_events(
            [post],
            _stream([PostExtraction(post_id=post.post_id, clues=[clue])]),
            Gazetteer(places_path=index),
            on_result=saved.update,
        )
    ]
    conclusions = next(data for name, data in events if name == "conclusions")
    assert conclusions["photo_place_results"][0]["status"] == "candidate"
    assert all(not claim.candidate_pool for claim in saved["profile_claims"])


def test_photo_home_area_candidate_snapshot_recalculates_and_hides_deleted_photo() -> None:
    photo_post = _post(1, text="\u81ea\u5b85\u8fd1\u304f\u306e\u67b6\u7a7a\u65bd\u8a2d")
    area_post = photo_post.model_copy(
        update={
            "post_id": "at://did:plc:xxxx/app.bsky.feed.post/2",
            "text": "\u6587\u4eac\u533a\u304c\u8fd1\u6240\u3067\u6bce\u65e5\u901a\u308b",
            "images": [],
        }
    )
    photo_clue = Clue(
        post_id=photo_post.post_id,
        image_index=0,
        type=ClueType.SHOP,
        value="\u67b6\u7a7a\u65bd\u8a2d",
        region=(1, 1, 9, 9),
        confidence=0.95,
        source=ClueSource.OCR,
    )
    area_clue = Clue(
        post_id=area_post.post_id,
        image_index=None,
        type=ClueType.PLACE_TEXT,
        value="\u6587\u4eac\u533a",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    photo_result = PhotoPlaceResult(
        post_id=photo_post.post_id,
        image_index=0,
        status=PhotoPlaceStatus.CANDIDATE,
        granularity=PhotoPlaceGranularity.FACILITY,
        lookup_status=PhotoPlaceLookupStatus.REFERENCE_CHECKED,
        candidates=[
            PhotoPlaceCandidate(
                place_id="fixture:place",
                label="\u67b6\u7a7a\u65bd\u8a2d",
                place_type=PhotoPlaceType.LANDMARK,
                photo_relation=PhotoPlaceRelation.VISIBLE_IN_FRAME,
                area_label="\u6587\u4eac\u533a",
                evidence=[PhotoPlaceEvidence(kind="clue", clue_index=0)],
                source_ids=["fixture:record"],
                sources=[
                    PhotoPlaceSource(
                        source_id="fixture:record",
                        provider="fixture",
                        dataset="places",
                        license_id="CC-BY-4.0",
                    )
                ],
            )
        ],
    )
    posts = [photo_post, area_post]
    clues = [photo_clue, area_clue]
    claims = infer_owner_candidate_sets_with_web(
        posts, clues, [], photo_place_results=[photo_result]
    )
    diagnosis = Diagnosis(
        posts=tuple(posts),
        clues=tuple(clues),
        photo_place_results=(photo_result,),
        profile_claims=tuple(claims),
    )

    class SnapshotStore:
        value = diagnosis

        def get_diagnosis(self, _: str) -> Diagnosis:
            return self.value

    store = SnapshotStore()
    snapshot = read_diagnosis(cast(SessionStore, store), "session", Gazetteer())
    assert len(snapshot["photo_place_results"]) == 1
    residential = next(
        item
        for item in snapshot["profile_claims"]
        if item["attribute"] == ProfileAttribute.RESIDENTIAL_AREA.value
    )
    assert [item["value"] for item in residential["candidates"]] == ["\u6587\u4eac\u533a"]

    for deleted_id in (photo_post.post_id, area_post.post_id):
        store.value = diagnosis.__class__(
            posts=diagnosis.posts,
            clues=diagnosis.clues,
            photo_place_results=diagnosis.photo_place_results,
            profile_claims=diagnosis.profile_claims,
            deleted=(deleted_id,),
        )
        restored = read_diagnosis(cast(SessionStore, store), "session", Gazetteer())
        restored_residential = next(
            item
            for item in restored["profile_claims"]
            if item["attribute"] == ProfileAttribute.RESIDENTIAL_AREA.value
        )
        assert restored_residential["candidates"] == []
        assert len(restored["photo_place_results"]) == (
            0 if deleted_id == photo_post.post_id else 1
        )


@pytest.mark.anyio
async def test_photo_home_area_claim_flows_through_sse_and_deletion_recalculation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    photo_post = _post(1, text="\u81ea\u5b85\u8fd1\u304f\u306e\u67b6\u7a7a\u65bd\u8a2d")
    area_post = photo_post.model_copy(
        update={
            "post_id": "at://did:plc:xxxx/app.bsky.feed.post/2",
            "text": "\u6587\u4eac\u533a\u304c\u8fd1\u6240\u3067\u6bce\u65e5\u901a\u308b",
            "images": [],
        }
    )
    photo_clue = Clue(
        post_id=photo_post.post_id,
        image_index=0,
        type=ClueType.SHOP,
        value="\u67b6\u7a7a\u65bd\u8a2d",
        region=(1, 1, 9, 9),
        confidence=0.95,
        source=ClueSource.OCR,
    )
    area_clue = Clue(
        post_id=area_post.post_id,
        image_index=None,
        type=ClueType.PLACE_TEXT,
        value="\u6587\u4eac\u533a",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    index = tmp_path / "places.sqlite3"
    record = {
        "place_id": "fixture:place",
        "label": "\u67b6\u7a7a\u65bd\u8a2d",
        "area_label": "\u6587\u4eac\u533a",
        "basic_category": "facility",
        "sources": [
            {
                "source_id": "fixture:record",
                "provider": "fixture",
                "dataset": "places",
                "license_id": "CC-BY-4.0",
                "record_id": "record",
                "version": "v1",
                "attribution": "fixture",
            }
        ],
    }
    with sqlite3.connect(index) as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
        db.executescript(
            "CREATE TABLE poi_place (place_id TEXT PRIMARY KEY, "
            "license_verified INTEGER NOT NULL, record_json TEXT NOT NULL);"
            "CREATE TABLE poi_alias (name_key TEXT NOT NULL, place_id TEXT NOT NULL, "
            "PRIMARY KEY(name_key, place_id));"
            "CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);"
        )
        db.execute(
            "INSERT INTO poi_place VALUES (?, 1, ?)",
            (record["place_id"], json.dumps(record, ensure_ascii=False)),
        )
        db.execute(
            "INSERT INTO poi_alias VALUES (?, ?)",
            ("\u67b6\u7a7a\u65bd\u8a2d", record["place_id"]),
        )

    saved: dict[str, Any] = {}

    async def inline_to_thread(function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    events = [
        event
        async for event in diagnose_events(
            [photo_post, area_post],
            _stream(
                [
                    PostExtraction(post_id=photo_post.post_id, clues=[photo_clue]),
                    PostExtraction(post_id=area_post.post_id, clues=[area_clue]),
                ]
            ),
            Gazetteer(places_path=index),
            on_result=saved.update,
        )
    ]
    conclusions = next(data for name, data in events if name == "conclusions")
    [photo_result] = conclusions["photo_place_results"]
    assert photo_result["status"] == "candidate"
    residential = next(
        claim
        for claim in conclusions["profile_claims"]
        if claim["attribute"] == ProfileAttribute.RESIDENTIAL_AREA.value
    )
    assert residential["status"] == "candidate"
    assert [candidate["value"] for candidate in residential["candidates"]] == ["\u6587\u4eac\u533a"]
    candidate = residential["candidates"][0]
    assert candidate["status"] == "weak"

    assert {ref["post_id"] for ref in candidate["evidence"] if ref["post_id"]} == {
        photo_post.post_id,
        area_post.post_id,
    }


@pytest.mark.anyio
async def test_conclusions_event_returns_photo_unknown_without_creating_profile_claims() -> None:
    post = _post(1)
    saved: dict[str, Any] = {}
    events = [
        event
        async for event in diagnose_events(
            [post],
            _stream([PostExtraction(post_id=post.post_id, clues=[])]),
            Gazetteer(),
            on_result=saved.update,
        )
    ]
    result = next(data for name, data in events if name == "conclusions")
    [photo_result] = result["photo_place_results"]
    assert photo_result["post_id"] == post.post_id
    assert photo_result["image_index"] == 0
    assert photo_result["status"] == "unknown"
    assert saved["photo_place_results"][0].status.value == "unknown"
    assert all(not claim.candidates for claim in saved["profile_claims"])


@pytest.mark.anyio
async def test_events_log_timings_without_post_contents(caplog: pytest.LogCaptureFixture) -> None:
    post = _post(2, text="毎週火曜はジム")
    clue = Clue(
        post_id=post.post_id,
        image_index=None,
        type=ClueType.ROUTINE_TEXT,
        value="毎週火曜はジム",
        region=None,
        confidence=0.9,
        source=ClueSource.TEXT,
    )
    ticks = iter([10.0, 13.5, 13.5, 13.75])

    with caplog.at_level("INFO", logger="tkb_api"):
        events = [
            e
            async for e in diagnose_events(
                [post],
                _stream([PostExtraction(post_id=post.post_id, clues=[clue])]),
                Gazetteer(),
                clock=lambda: next(ticks),
            )
        ]

    assert events[-1][0] == "done"
    messages = [r.getMessage() for r in caplog.records]
    assert messages == [
        "診断 1/1 件目：3.5 秒（写真 2 枚、手がかり 1 件）",
        "診断の時間：手がかりの取り出し 3.5 秒（投稿 1 件、写真 2 枚、手がかり 1 件、失敗 0 件）"
        "、推理と危ない投稿 0.25 秒",
    ]
    # 投稿の ID・本文・手がかりの中身はログに出さない
    assert not any(post.post_id in m or "ジム" in m for m in messages)


@pytest.mark.anyio
async def test_events_run_inference_and_planning_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 推理と危ない投稿の選び方は別のスレッドで動き、その間もイベントループは止まらない
    import threading

    from tkb_api import pipeline
    from tkb_engine.rules import infer as real_infer

    loop_thread = threading.get_ident()
    threads: dict[str, int] = {}
    real_plan_claims_json = pipeline.plan_claims_json

    def infer(*args: Any) -> Any:
        threads["infer"] = threading.get_ident()
        return real_infer(*args)

    def plan_claims_json(*args: Any, **kwargs: Any) -> Any:
        threads["plan_claims_json"] = threading.get_ident()
        return real_plan_claims_json(*args, **kwargs)

    monkeypatch.setattr(pipeline, "infer", infer)
    monkeypatch.setattr(pipeline, "plan_claims_json", plan_claims_json)
    post = _post(0)
    events = [
        e
        async for e in diagnose_events(
            [post], _stream([PostExtraction(post_id=post.post_id, clues=[])]), Gazetteer()
        )
    ]

    assert [name for name, _ in events][-3:] == ["conclusions", "plan", "done"]
    assert set(threads) == {"infer", "plan_claims_json"}
    assert loop_thread not in threads.values()
