"""data-prep の表（stations・postal・muni_mesh）と知識表、手がかりの値の引き当て。

表は `make data` で data/processed/ に作る（コミットしない）。
知識表（指定ゴミ袋・ゴミの収集地区・大学）は手で作る小さな表で、data-prep/manual/knowledge.json
に置く。どの行にも出典（source）を書く。
テストでは Gazetteer を直接組み立てる。
"""

import dataclasses
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from tkb_common.schemas import Clue, ClueType

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"
KNOWLEDGE_PATH = Path(__file__).resolve().parents[3] / "data-prep" / "manual" / "knowledge.json"


@dataclass(frozen=True)
class TrashBag:
    """自治体の指定ゴミ袋。price は1枚の値段（円）。color は分からなければ空。"""

    city: str
    liters: int
    price: float
    kind: str = ""
    color: str = ""


@dataclass(frozen=True)
class CollectionArea:
    """ゴミの収集地区。burnable_days は燃やすごみの曜日（「水土」のように曜日の字を並べる。
    分からなければ空）。towns はその地区の町名（「子安町1・3・4丁目」のような書き方のまま）。"""

    city: str
    area: str
    burnable_days: str
    towns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class University:
    """大学のキャンパス。periods は時限 → (始まり, 終わり)。時刻は時の小数（10:50 → 10.8333）。"""

    name: str
    campus: str
    city: str
    periods: dict[int, tuple[float, float]]


@dataclass(frozen=True)
class Knowledge:
    trash_bags: list[TrashBag] = field(default_factory=list)
    collection_areas: list[CollectionArea] = field(default_factory=list)
    universities: list[University] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = KNOWLEDGE_PATH) -> "Knowledge":
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            trash_bags=[TrashBag(**_fields(r, TrashBag)) for r in doc["trash_bags"]],
            collection_areas=[
                CollectionArea(**_fields(r, CollectionArea)) for r in doc["collection_areas"]
            ],
            universities=[
                University(
                    name=r["name"],
                    campus=r["campus"],
                    city=r["city"],
                    periods={int(k): (_hours(a), _hours(b)) for k, (a, b) in r["periods"].items()},
                )
                for r in doc["universities"]
            ],
        )


def _fields(row: dict[str, Any], cls: type[Any]) -> dict[str, Any]:
    """出典（source）などの説明の列を落とす。"""
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in row.items() if k in names}


def _hours(hhmm: str) -> float:
    h, m = hhmm.split(":")
    return int(h) + int(m) / 60


@dataclass(frozen=True)
class Gazetteer:
    """推理ルールが引く表。

    - stations：駅ごとに {"station_name", "mesh_1km", ...}
    - postal：郵便番号ごとに {"postal_code"（ハイフンなし7桁）, "muni_code", "city", "town", ...}
    - muni_meshes：区市町村コード → その区市町村にかかる 1km メッシュの集合
    """

    stations: list[dict[str, Any]] = field(default_factory=list)
    postal: list[dict[str, str]] = field(default_factory=list)
    muni_meshes: dict[str, set[str]] = field(default_factory=dict)
    knowledge: Knowledge = field(default_factory=Knowledge)
    # 学校ごとに {"name", "kind"（大学・高等学校など）, "city", ...}。表がなければ空
    schools: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR, knowledge: Knowledge | None = None) -> "Gazetteer":
        meshes: dict[str, set[str]] = {}
        for row in pq.read_table(data_dir / "muni_mesh.parquet").to_pylist():
            meshes.setdefault(row["muni_code"], set()).add(row["mesh_1km"])
        return cls(
            stations=pq.read_table(data_dir / "stations.parquet").to_pylist(),
            postal=pq.read_table(data_dir / "postal.parquet").to_pylist(),
            muni_meshes=meshes,
            knowledge=Knowledge.load() if knowledge is None else knowledge,
            schools=(
                pq.read_table(data_dir / "schools.parquet").to_pylist()
                if (data_dir / "schools.parquet").is_file()
                else []
            ),
        )

    def city_munis(self, city: str) -> set[str]:
        """市区町村名（「八王子市」など）の区市町村コード。"""
        return {r["muni_code"] for r in self.postal if r["city"] == city}

    def cities_in(self, text: str) -> set[str]:
        """文字の中に出てくる市区町村名（郵便番号の表と知識表にあるもの）。"""
        names = {r["city"] for r in self.postal} | {b.city for b in self.knowledge.trash_bags}
        found = {name for name in names if name and name in text}
        # 「八王子市」と「王子市」のように、ほかの名前に含まれるものは落とす
        return {n for n in found if not any(n != m and n in m for m in found)}

    def schools_named_in(self, text: str) -> list[dict[str, str]]:
        """文字の中に名前（「〇〇高等学校」「〇〇高校」「都立〇〇高校」なども）が出てくる学校。
        ほかの名前の一部になっている短い名前は落とす。"""
        hits = [
            (variant, s)
            for s in self.schools
            for variant in school_name_variants(s["name"])
            if variant in text
        ]
        longest = max((len(v) for v, _ in hits), default=0)
        found = {s["name"]: s for v, s in hits if len(v) == longest}
        return list(found.values())

    def postal_rows(self, code: str) -> list[dict[str, str]]:
        """ハイフンなし7桁の郵便番号の行。"""
        return [r for r in self.postal if r["postal_code"] == code]

    def station_names(self, value: str) -> set[str]:
        """駅名の手がかり（「根x」「根津駅」など）に合う駅名。"""
        pattern = _pattern(value.strip().removesuffix("駅"))
        return {s["station_name"] for s in self.stations if pattern.fullmatch(s["station_name"])}

    def station_point(self, name: str) -> tuple[float, float] | None:
        """駅（同じ名前の駅をまとめた中心）の緯度経度。同じ名前の別の場所の駅がある
        （中心から STATION_SPREAD_KM より離れた行がある）か、緯度経度がなければ None。"""
        rows = [s for s in self.stations if s["station_name"] == name and s.get("lat") is not None]
        return _center(rows, STATION_SPREAD_KM)

    def city_point(self, city: str) -> tuple[float, float] | None:
        """市区町村の中にある駅の中心（市区町村の代わりの位置）。"""
        meshes = set().union(*(self.muni_meshes.get(m, set()) for m in self.city_munis(city)))
        rows = [s for s in self.stations if s["mesh_1km"] in meshes and s.get("lat") is not None]
        return _center(rows, None)

    def stations_named_in(self, text: str) -> set[str]:
        """文字の中に出てくる駅名。2文字以上で、ほかに見つかった駅名の一部になっているものは落とす
        （「東中野」があれば「中野」は落とす）。"""
        found = {
            s["station_name"]
            for s in self.stations
            if len(s["station_name"]) >= 2 and s["station_name"] in text
        }
        return {n for n in found if not any(n != m and n in m for m in found)}

    def stations_in(self, muni_codes: set[str]) -> set[str]:
        """区市町村のメッシュにある駅名。"""
        meshes = set().union(*(self.muni_meshes.get(m, set()) for m in muni_codes))
        return {s["station_name"] for s in self.stations if s["mesh_1km"] in meshes}

    def area(self, clue: Clue) -> tuple[set[str], set[str]]:
        """住所・郵便番号の手がかりに合う、区市町村コードと町名の候補。"""
        if clue.type is ClueType.POSTAL_CODE:
            pattern = _pattern(clue.value.replace("-", ""))
            rows = [r for r in self.postal if pattern.fullmatch(r["postal_code"])]
        else:
            value = clue.value.replace(" ", "")
            rows = [
                r
                for r in self.postal
                if r["city"] in value
                and _town(r["town"])
                and value.split(r["city"], 1)[1].startswith(_town(r["town"]))
            ]
        return {r["muni_code"] for r in rows}, {_town(r["town"]) for r in rows}


def school_name_variants(name: str) -> set[str]:
    """学校の正式名から、写真や本文に出てきそうな書き方。短すぎるもの（2文字以下）は入れない。"""
    base = re.sub(
        r"^(東京都立|都立|神奈川県立|県立|千葉県立|埼玉県立|市立|区立|国立|私立)", "", name
    )
    variants = {name, base}
    for long, short in (("高等学校", "高校"), ("中等教育学校", "中等")):
        if base.endswith(long):
            stem = base.removesuffix(long)
            variants.add(stem + short)
            if name.startswith(("東京都立", "都立")):
                variants.add("都立" + stem + short)
    return {v for v in variants if len(v) > 2}


# 同じ名前の駅をまとめるとき、中心からこれより離れた行があれば別の場所の駅とみなす
STATION_SPREAD_KM = 3.0


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """2点（緯度, 経度）の距離（km）。"""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def _center(rows: list[dict[str, Any]], spread_km: float | None) -> tuple[float, float] | None:
    if not rows:
        return None
    center = (
        sum(float(r["lat"]) for r in rows) / len(rows),
        sum(float(r["lon"]) for r in rows) / len(rows),
    )
    if spread_km is not None and any(
        distance_km(center, (float(r["lat"]), float(r["lon"]))) > spread_km for r in rows
    ):
        return None
    return center


def _pattern(value: str) -> re.Pattern[str]:
    """読めない文字の x を1文字として扱う。"""
    return re.compile("".join("." if ch == "x" else re.escape(ch) for ch in value))


def _town(town: str) -> str:
    """「弥生（次のビルを除く）」のような括弧書きを落とす。"""
    return re.sub(r"（.*）$", "", town)
