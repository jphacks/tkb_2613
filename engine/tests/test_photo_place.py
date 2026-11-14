import json
import sqlite3
from pathlib import Path
from typing import Any

from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION, place_name_keys
from tkb_common.schemas import Clue, ClueSource, ClueType, PhotoPlaceRelation, Post
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.photo_place import infer_photo_places

POST = Post.model_validate(
    {
        "post_id": "at://did:plc:demo/app.bsky.feed.post/place",
        "text": "",
        "created_at": "2026-11-01T12:00:00+09:00",
        "images": [
            {
                "index": 0,
                "url": "https://cdn.bsky.app/img/feed_fullsize/demo",
                "alt": "",
                "width": 100,
                "height": 100,
            }
        ],
    }
)


def _clue(kind: ClueType, text: str) -> Clue:
    return Clue(
        post_id=POST.post_id,
        image_index=0,
        type=kind,
        value=text,
        region=(1, 1, 20, 20),
        confidence=0.9,
        source=ClueSource.OCR,
    )


def _poi_index(
    path: Path,
    records: list[dict[str, Any]],
    *,
    schema_version: int = PLACE_INDEX_SCHEMA_VERSION,
) -> None:
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {schema_version}")
        db.executescript(
            "CREATE TABLE poi_place (place_id TEXT PRIMARY KEY, "
            "license_verified INTEGER NOT NULL, record_json TEXT NOT NULL);"
            "CREATE TABLE poi_alias (name_key TEXT NOT NULL, place_id TEXT NOT NULL, "
            "PRIMARY KEY(name_key, place_id));"
            "CREATE INDEX poi_alias_name_idx ON poi_alias(name_key);"
        )
        for record in records:
            sources = record.get("sources", [])
            licensed = bool(sources) and all(source.get("license_id") for source in sources)
            db.execute(
                "INSERT INTO poi_place VALUES (?, ?, ?)",
                (record["place_id"], int(licensed), json.dumps(record, ensure_ascii=False)),
            )
            names = [record.get("label", "中央文化会館"), *record.get("aliases", ["中央文化会館"])]
            db.executemany(
                "INSERT OR IGNORE INTO poi_alias VALUES (?, ?)",
                ((key, record["place_id"]) for name in names for key in place_name_keys(str(name))),
            )


def test_optional_poi_index_emits_visible_candidate_with_source_and_no_score(
    tmp_path: Path,
) -> None:
    index = tmp_path / "places.sqlite3"
    source = {
        "source_id": "fixture:poi-1",
        "provider": "fixture",
        "dataset": "places",
        "license_id": "CC-BY-4.0",
        "record_id": "poi-1",
        "version": "v1",
        "attribution": "Fixture",
    }
    record = {
        "place_id": "places:poi-1",
        "label": "中央文化館",
        "sources": [source],
        "basic_category": "cultural",
    }
    _poi_index(index, [record])
    clue = _clue(ClueType.SHOP, "中央文化会館")

    [result] = infer_photo_places([POST], [clue], Gazetteer(places_path=index))

    assert result.status.value == "candidate"
    [candidate] = result.candidates
    assert candidate.photo_relation is PhotoPlaceRelation.VISIBLE_IN_FRAME
    assert candidate.score is None
    assert candidate.sources[0].license_id == "CC-BY-4.0"
    assert candidate.evidence[0].clue_index == 0


def test_duplicate_poi_names_are_ambiguous_and_absent_index_is_unknown(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    records = [
        {
            "place_id": f"places:{item}",
            "label": f"中央文化館 {item}",
            "sources": [
                {
                    "source_id": f"fixture:{item}",
                    "provider": "Fixture",
                    "dataset": "places",
                    "license_id": "CC-BY-4.0",
                    "record_id": item,
                    "version": None,
                    "attribution": "Fixture",
                }
            ],
            "basic_category": "cultural",
        }
        for item in ("a", "b")
    ]
    _poi_index(index, records)
    clue = _clue(ClueType.LANDMARK, "中央文化会館")
    [ambiguous] = infer_photo_places([POST], [clue], Gazetteer(places_path=index))
    [unknown] = infer_photo_places([POST], [clue], Gazetteer())
    assert ambiguous.status.value == "ambiguous"
    assert len(ambiguous.candidates) == 2
    assert unknown.status.value == "unknown"


def test_person_name_clue_does_not_query_poi_index(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _poi_index(index, [{"place_id": "places:p", "label": "太郎", "sources": []}])
    clue = _clue(ClueType.NAME_TEXT, "太郎")
    [result] = infer_photo_places([POST], [clue], Gazetteer(places_path=index))
    assert result.status.value == "unknown"


def test_unlicensed_poi_record_is_not_a_search_candidate(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _poi_index(
        index,
        [
            {
                "place_id": "places:p",
                "label": "中央文化館",
                "sources": [
                    {
                        "source_id": "provider:p",
                        "provider": "Provider",
                        "dataset": "places",
                        "license_id": None,
                        "record_id": "p",
                        "version": None,
                        "attribution": None,
                    }
                ],
            }
        ],
    )
    [result] = infer_photo_places(
        [POST], [_clue(ClueType.SHOP, "中央文化会館")], Gazetteer(places_path=index)
    )
    assert result.status.value == "unknown"


def test_place_lookup_accepts_kana_and_spacing_variants_but_not_kanji_readings(
    tmp_path: Path,
) -> None:
    index = tmp_path / "places.sqlite3"
    _poi_index(
        index,
        [
            {
                "place_id": "places:variant",
                "label": "東京・文化 館",
                "aliases": [],
                "sources": [
                    {
                        "source_id": "fixture:variant",
                        "provider": "fixture",
                        "dataset": "places",
                        "license_id": "CC-BY-4.0",
                        "record_id": "variant",
                        "version": None,
                        "attribution": None,
                    }
                ],
            }
        ],
    )
    gazetteer = Gazetteer(places_path=index)

    assert [row["place_id"] for row in gazetteer.places_named("東京 文化館")] == ["places:variant"]
    assert [row["place_id"] for row in gazetteer.places_named("東京･文化館")] == ["places:variant"]
    assert gazetteer.places_named("とうきょう文化館") == []


def test_normalization_collision_stays_ambiguous(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    records = []
    for place_id, label in (
        ("places:dot", "中央・文化会館"),
        ("places:plain", "中央文化会館"),
    ):
        records.append(
            {
                "place_id": place_id,
                "label": label,
                "aliases": [],
                "sources": [
                    {
                        "source_id": f"fixture:{place_id}",
                        "provider": "fixture",
                        "dataset": "places",
                        "license_id": "CC-BY-4.0",
                        "record_id": place_id,
                        "version": None,
                        "attribution": None,
                    }
                ],
            }
        )
    _poi_index(index, records)

    [result] = infer_photo_places(
        [POST], [_clue(ClueType.SHOP, "中央・文化会館")], Gazetteer(places_path=index)
    )

    assert result.status.value == "ambiguous"
    assert {candidate.place_id for candidate in result.candidates} == {
        "places:dot",
        "places:plain",
    }


def test_old_place_index_schema_returns_unknown_with_reason(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    _poi_index(index, [], schema_version=PLACE_INDEX_SCHEMA_VERSION - 1)

    [result] = infer_photo_places(
        [POST], [_clue(ClueType.SHOP, "中央文化会館")], Gazetteer(places_path=index)
    )

    assert result.status.value == "unknown"
    assert result.reason_codes == ["poi_index_schema_mismatch"]


def test_too_many_same_name_pois_are_bounded_and_explicitly_ambiguous(tmp_path: Path) -> None:
    index = tmp_path / "places.sqlite3"
    records = []
    for number in range(55):
        place_id = f"places:{number}"
        records.append(
            {
                "place_id": place_id,
                "label": "中央文化館",
                "sources": [
                    {
                        "source_id": f"provider:{number}",
                        "provider": "Provider",
                        "dataset": "places",
                        "license_id": "CC-BY-4.0",
                        "record_id": str(number),
                        "version": None,
                        "attribution": None,
                    }
                ],
            }
        )
    _poi_index(index, records)
    [result] = infer_photo_places(
        [POST], [_clue(ClueType.SHOP, "中央文化会館")], Gazetteer(places_path=index)
    )
    assert result.status.value == "ambiguous"
    assert result.reason_codes == ["multiple_matches", "too_many_matches"]
    assert len(result.candidates) == 50
