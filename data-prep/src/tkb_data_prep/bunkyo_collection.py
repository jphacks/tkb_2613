"""文京区の町丁目ごとのごみの収集日を、手作りの知識表（manual/knowledge.json）の収集地区の行にする。

入力は文京区のオープンデータ「ごみと資源の収集日」（syusyubi.csv、Shift_JIS、CC BY 4.0）。
fetch.sh で data-prep/raw/bunkyo/syusyubi.csv に取得する。列は 町名, 丁目, 可燃ごみ（週2回）, …。
行ごとに「弥生1・2丁目」のような地区を作り、燃やすごみの曜日（「月木」）と出典を書く。

知識表は推理ルールが引く小さな表でコミットするので、変換した行をそこに書き込む
（ほかの自治体の行と、文京区以外の表はそのまま残す）。文京区の CSV が更新されたら、
もう一度実行する：

uv run python -m tkb_data_prep.bunkyo_collection
"""

import copy
import json
import sys
from typing import Any

from tkb_data_prep.config import Paths
from tkb_data_prep.errors import DataPrepError
from tkb_data_prep.io import read_csv

CITY = "文京区"
URL = "https://www.city.bunkyo.lg.jp/documents/6059/syusyubi.csv"
SOURCE = (
    f"文京区オープンデータ「ごみと資源の収集日」（{URL}、CC BY 4.0、"
    "2026-03-23 更新のファイルを 2026-11-12 に取得）を加工して作成。町丁目ごとの可燃ごみの曜日"
)
WEEKDAYS = "月火水木金土日"
BURNABLE_PREFIX = "可燃ごみ"


def parse(rows: list[list[str]]) -> list[dict[str, Any]]:
    header = [cell.strip() for cell in rows[0]] if rows else []
    burnable = next((i for i, h in enumerate(header) if h.startswith(BURNABLE_PREFIX)), None)
    if burnable is None or "町名" not in header or "丁目" not in header:
        raise DataPrepError(f"文京区の収集日の CSV の見出しが想定外です: {header}")
    town, block = header.index("町名"), header.index("丁目")
    areas = []
    for row in rows[1:]:
        if len(row) <= max(burnable, town, block) or not row[town].strip():
            continue
        name = row[town].strip() + row[block].strip()
        days = "".join(d for d in WEEKDAYS if d in row[burnable].replace("曜日", ""))
        areas.append(
            {"city": CITY, "area": name, "burnable_days": days, "towns": [name], "source": SOURCE}
        )
    return areas


def merge(knowledge: dict[str, Any], areas: list[dict[str, Any]]) -> dict[str, Any]:
    """文京区の収集地区の行だけを入れ替えた、新しい知識表。"""
    updated = copy.deepcopy(knowledge)
    kept = [a for a in updated.get("collection_areas", []) if a.get("city") != CITY]
    updated["collection_areas"] = [*kept, *areas]
    return updated


def update(paths: Paths) -> int:
    path = paths.bunkyo_collection_csv
    if not path.is_file():
        print(f"{path} がありません。先に data-prep/fetch.sh で取得してください", file=sys.stderr)
        return 1
    knowledge_path = paths.manual_dir / "knowledge.json"
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    areas = parse(read_csv(path))
    knowledge_path.write_text(
        json.dumps(merge(knowledge, areas), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{knowledge_path} に文京区の収集地区を {len(areas)} 行書きました")
    return 0


if __name__ == "__main__":
    sys.exit(update(Paths()))
