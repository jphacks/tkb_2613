import json
from pathlib import Path
from typing import Any

import pytest

from tkb_data_prep import bunkyo_collection
from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError

HEADER = [
    "町名",
    "丁目",
    "可燃ごみ（週2回）",
    "不燃ごみ（月2回）",
    "資源（…）（週1回）",
    "資源（プラスチック）（週1回）",
    "説明",
]


def test_parse_turns_each_town_row_into_a_collection_area() -> None:
    rows = [
        HEADER,
        ["弥生", "1・2丁目", "月曜日・木曜日", "第1・第3水曜日", "火曜日", "金曜日", "説明"],
        ["小石川", "1丁目1～16番", "月曜日・木曜日", "第1・第3水曜日", "火曜日", "金曜日", "説明"],
    ]

    areas = bunkyo_collection.parse(rows)

    assert areas[0] == {
        "city": "文京区",
        "area": "弥生1・2丁目",
        "burnable_days": "月木",
        "towns": ["弥生1・2丁目"],
        "source": bunkyo_collection.SOURCE,
    }
    assert areas[1]["area"] == "小石川1丁目1～16番"


def test_parse_needs_the_burnable_column() -> None:
    with pytest.raises(DataPrepError):
        bunkyo_collection.parse([["町名", "丁目"], ["弥生", "1丁目"]])


def test_merge_replaces_only_the_bunkyo_rows(tmp_path: Path) -> None:
    knowledge: dict[str, Any] = {
        "note": "x",
        "collection_areas": [
            {
                "city": "八王子市",
                "area": "収集地区1",
                "burnable_days": "",
                "towns": [],
                "source": "s",
            },
            {"city": "文京区", "area": "古い行", "burnable_days": "", "towns": [], "source": "s"},
        ],
    }
    new = [
        {
            "city": "文京区",
            "area": "弥生1・2丁目",
            "burnable_days": "月木",
            "towns": [],
            "source": "t",
        }
    ]

    merged = bunkyo_collection.merge(knowledge, new)

    assert [a["area"] for a in merged["collection_areas"]] == ["収集地区1", "弥生1・2丁目"]
    assert knowledge["collection_areas"][1]["area"] == "古い行"  # 元の辞書は変えない


def test_main_updates_the_knowledge_file(tmp_path: Path) -> None:
    paths = Paths(raw_dir=tmp_path / "raw", manual_dir=tmp_path / "manual")
    paths.manual_dir.mkdir()
    knowledge_path = paths.manual_dir / "knowledge.json"
    knowledge_path.write_text(json.dumps({"collection_areas": []}), encoding="utf-8")
    assert bunkyo_collection.update(paths) == 1  # CSV がない
    paths.bunkyo_collection_csv.parent.mkdir(parents=True)
    text = ",".join(HEADER) + "\r\n" + "弥生,1・2丁目,月曜日・木曜日,a,b,c,d\r\n"
    paths.bunkyo_collection_csv.write_bytes(text.encode("cp932"))

    assert bunkyo_collection.update(paths) == 0

    doc = json.loads(knowledge_path.read_text(encoding="utf-8"))
    assert [a["area"] for a in doc["collection_areas"]] == ["弥生1・2丁目"]
