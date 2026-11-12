"""data-prep の表（stations・postal・muni_mesh）と知識表、手がかりの値の引き当て。

表は `make data` で data/processed/ に作る（コミットしない）。
知識表（指定ゴミ袋・ゴミの収集地区・大学）は手で作る小さな表で、data-prep/manual/knowledge.json
に置く。どの行にも出典（source）を書く。
テストでは Gazetteer を直接組み立てる。
"""

import dataclasses
import functools
import json
import math
import re
import sqlite3
import unicodedata
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from tkb_common.corporate_name import normalize_corporate_name
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
    """大学のキャンパス。periods は時限 → (始まり, 終わり)。時刻は時の小数（10:50 → 10.8333）。
    stations はキャンパスの最寄り駅（大学のアクセス案内に書かれた駅）。"""

    name: str
    campus: str
    city: str
    periods: dict[int, tuple[float, float]]
    stations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Knowledge:
    trash_bags: list[TrashBag] = field(default_factory=list)
    collection_areas: list[CollectionArea] = field(default_factory=list)
    universities: list[University] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "Knowledge":
        # 開発時はソースの相対位置、Dockerの非editableインストール時は起動場所から読む。
        if path is None:
            path = (
                KNOWLEDGE_PATH
                if KNOWLEDGE_PATH.is_file()
                else Path("data-prep/manual/knowledge.json")
            )
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
                    periods={
                        int(k): (_hours(a), _hours(b)) for k, (a, b) in r.get("periods", {}).items()
                    },
                    stations=r.get("stations", []),
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


# 「線」だけや1文字の路線名で、関係のない文字に合わないようにする
MIN_LINE_NAME_LENGTH = 3


@dataclass(frozen=True)
class Gazetteer:
    """推理ルールが引く表。

    - stations：駅ごとに {"station_name", "mesh_1km", "line_name", ...}（駅と路線の組ごとに1行）
    - postal：郵便番号ごとに {"postal_code"（ハイフンなし7桁）, "muni_code", "city", "town", ...}
    - muni_meshes：区市町村コード → その区市町村にかかる 1km メッシュの集合
    """

    stations: list[dict[str, Any]] = field(default_factory=list)
    postal: list[dict[str, str]] = field(default_factory=list)
    muni_meshes: dict[str, set[str]] = field(default_factory=dict)
    knowledge: Knowledge = field(default_factory=Knowledge)
    # 学校ごとに {"name", "kind"（大学・高等学校など）, "city", ...}。表がなければ空
    schools: list[dict[str, str]] = field(default_factory=list)
    # 国土地理院の指定緊急避難場所・指定避難所。{"name", "kind", "muni_code", "city", ...}。
    # 表がなければ空
    shelters: list[dict[str, Any]] = field(default_factory=list)
    # 国土数値情報のバス停留所（令和4年度版）。{"name", "operator", "cities"（1km メッシュに
    # かかる区市町村の候補）, ...}。表がなければ空
    bus_stops: list[dict[str, Any]] = field(default_factory=list)
    # 国土数値情報の小学校区・中学校区（令和3年度版）。{"kind"（小学校・中学校）, "name", "city",
    # "terms"（自治体ごとの利用条件）, "note"（条件の原文）}。表がなければ空
    school_districts: list[dict[str, Any]] = field(default_factory=list)
    # 法人番号の公表データの SQLite（data-prep の corporations.sqlite）。行はメモリに載せず、
    # 引くたびに読み取り専用で開く。なければ None
    corporations_path: Path | None = None

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
            schools=_optional_table(data_dir / "schools.parquet"),
            shelters=_optional_table(data_dir / "shelters.parquet", SHELTER_COLUMNS),
            bus_stops=_optional_table(data_dir / "bus_stops.parquet", BUS_STOP_COLUMNS),
            school_districts=_optional_table(
                data_dir / "school_districts.parquet", SCHOOL_DISTRICT_COLUMNS
            ),
            corporations_path=(
                data_dir / "corporations.sqlite"
                if (data_dir / "corporations.sqlite").is_file()
                else None
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

    @functools.cached_property
    def _shelters_by_variant(self) -> dict[str, list[dict[str, Any]]]:
        by_variant: dict[str, list[dict[str, Any]]] = {}
        for row in self.shelters:
            for variant in shelter_name_variants(str(row["name"])):
                by_variant.setdefault(variant, []).append(row)
        return by_variant

    def shelters_named_at(self, text: str) -> dict[str, list[dict[str, Any]]]:
        """文字の先頭に名前が書かれた避難所。名前の核（shelter_core_name）→ 同じ核の施設の行。
        先頭の「指定避難所」などの見出しと「〇〇区立」は飛ばす。長い名前の一部
        （「新宿中央公園」の「中央公園」）には合わせないよう、先頭からの一致だけを見て、
        いちばん長い名前を返す。同じ名前の施設が別の区市町村にもあるときは、その行がすべて入る
        （使う側で競合として捨てる）。"""
        normalized = _SHELTER_LABEL.sub("", _normalize_name(text))
        heads = {normalized, _MUNICIPAL_PREFIX.sub("", normalized)}
        found = {
            v: rows
            for v, rows in self._shelters_by_variant.items()
            if any(head.startswith(v) for head in heads)
        }
        longest = max((len(v) for v in found), default=0)
        cores = {
            shelter_core_name(str(row["name"]))
            for v, rows in found.items()
            if len(v) == longest
            for row in rows
        }
        return {core: self._shelters_by_core[core] for core in cores}

    @functools.cached_property
    def _shelters_by_core(self) -> dict[str, list[dict[str, Any]]]:
        by_core: dict[str, list[dict[str, Any]]] = {}
        for row in self.shelters:
            by_core.setdefault(shelter_core_name(str(row["name"])), []).append(row)
        return by_core

    @functools.cached_property
    def _bus_stops_by_name(self) -> dict[str, list[dict[str, Any]]]:
        by_name: dict[str, list[dict[str, Any]]] = {}
        for row in self.bus_stops:
            name = _normalize_name(re.sub(r"[（(].*?[）)]", "", str(row["name"])))
            if len(name) >= MIN_BUS_STOP_NAME_LENGTH:
                by_name.setdefault(name, []).append(row)
        return by_name

    def bus_stops_named_at(self, text: str) -> dict[str, list[dict[str, Any]]]:
        """文字の先頭に名前が書かれたバス停。名前 → 同じ名前のバス停の行（事業者・場所が違うものも
        すべて）。長い名前の一部（「西根津一丁目」の「根津一丁目」）には合わせない。"""
        head = _normalize_name(text)
        found = [name for name in self._bus_stops_by_name if head.startswith(name)]
        if not found:
            return {}
        name = max(found, key=len)
        return {name: self._bus_stops_by_name[name]}

    @functools.cached_property
    def _districts_by_name(self) -> dict[str, list[dict[str, Any]]]:
        by_name: dict[str, list[dict[str, Any]]] = {}
        for row in self.school_districts:
            by_name.setdefault(_school_key(str(row["name"])), []).append(row)
        return by_name

    def districts_of_school(self, name: str) -> list[dict[str, Any]]:
        """学校名（「文京区立根津小学校」「根津小」も）の学区の行。同じ名前の学校がほかの
        区市町村にもあれば、その行もすべて入る（使う側で競合として捨てる）。"""
        return self._districts_by_name.get(_school_key(name), [])

    def corporations_named(self, name: str) -> list[tuple[str, str]]:
        """正規化した名前が一致する法人の (法人番号, 商号)。表がなければ空。部分一致はしない。"""
        normalized = normalize_corporate_name(name)
        if not normalized:
            return []
        rows = self._query_corporations(
            "SELECT DISTINCT corporate_number, name FROM corporations WHERE normalized_name = ?",
            (normalized,),
        )
        return [(str(number), str(legal)) for number, legal in rows]

    def corporations_as_of(self) -> str:
        """法人番号の表の時点（「2026-10-30」）。わからなければ空。"""
        rows = self._query_corporations("SELECT value FROM meta WHERE key = 'as_of'", ())
        return str(rows[0][0]) if rows else ""

    def _query_corporations(self, sql: str, params: tuple[str, ...]) -> list[tuple[Any, ...]]:
        if self.corporations_path is None:
            return []
        # 本番では読み取り専用でマウントされるので、immutable で開く（ロックのファイルを作らない）
        uri = f"{self.corporations_path.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            return db.execute(sql, params).fetchall()

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

    def lines_of(self, station_name: str) -> set[str]:
        """駅が乗っている路線の名前（「9号線千代田線」は「千代田線」にする）。"""
        return {
            _line(s["line_name"])
            for s in self.stations
            if s["station_name"] == station_name and s.get("line_name")
        }

    def line_names(self, value: str) -> set[str]:
        """手がかりの文字（「千代田線また遅延」など）に出てくる路線の名前。"""
        text = value.replace(" ", "")
        lines = {_line(s["line_name"]) for s in self.stations if s.get("line_name")}
        return {line for line in lines if len(line) >= MIN_LINE_NAME_LENGTH and line in text}

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


# 避難所の名前から取り除く、建物や場所の部分（「〇〇小学校体育館」→「〇〇小学校」）
_SHELTER_PART = re.compile(
    r"(?:の)?(?:第?[0-9一二三]?体育館|屋内運動場|校庭|グラウンド|グランド|校舎|講堂|運動場|プール)$"
)
_MUNICIPAL_PREFIX = re.compile(r"^(?:.{1,6}?[都道府県区市町村]立)")
# 掲示などで名前の前に書かれる見出し（「指定避難所 〇〇小学校」）
_SHELTER_LABEL = re.compile(r"^(?:[指定広域緊急一時]{0,6}避難(?:場所|所)[:：・]?)+")
# 手がかりの文字に合わせる名前の最短の長さ（「西公園」のような短い名前は合わせない）
MIN_SHELTER_NAME_LENGTH = 4
# バス停の名前の最短の長さ（「本町」「駅前」のような短い名前は合わせない）
MIN_BUS_STOP_NAME_LENGTH = 3


def shelter_core_name(name: str) -> str:
    """括弧書き、建物の部分、「〇〇区立」を落とした名前。同じ施設の書き方の違いをまとめる。"""
    base = _normalize_name(re.sub(r"[（(].*?[）)]", "", name))
    return _MUNICIPAL_PREFIX.sub("", _SHELTER_PART.sub("", base))


def shelter_name_variants(name: str) -> set[str]:
    """避難所の名前から、投稿や写真に出てきそうな書き方。括弧書き、「〇〇区立」、
    「体育館」などの建物の部分を落とした形も入れる。短すぎるものは入れない。"""
    base = _normalize_name(re.sub(r"[（(].*?[）)]", "", name))
    variants = {base}
    for v in list(variants):
        variants.add(_SHELTER_PART.sub("", v))
    for v in list(variants):
        variants.add(_MUNICIPAL_PREFIX.sub("", v))
    return {v for v in variants if len(v) >= MIN_SHELTER_NAME_LENGTH}


def _normalize_name(text: str) -> str:
    """互換漢字、「ヶ」と「ケ」、空白をそろえる。"""
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", text)).replace("ヶ", "ケ")


def _optional_table(path: Path, columns: list[str] | None = None) -> list[dict[str, Any]]:
    """公開データの表は、ないとき（テスト、CI、取得前）は空として扱う。columns を渡すと、
    推定に使う列だけを読む（api の常駐メモリを減らすため。座標などは読まない）。"""
    return pq.read_table(path, columns=columns).to_pylist() if path.is_file() else []


# 公開データの表から読む列（推定に使うものだけ）
SHELTER_COLUMNS = ["name", "kind", "city"]
BUS_STOP_COLUMNS = ["name", "operator", "cities"]
SCHOOL_DISTRICT_COLUMNS = ["kind", "name", "city", "terms", "note"]


def _school_key(name: str) -> str:
    """学校名を引くための形。「〇〇区立」を落とし、「根津小」「根津中」は「〜学校」にそろえる。"""
    key = _MUNICIPAL_PREFIX.sub("", _normalize_name(name))
    if key.endswith(("小", "中")):
        key += "学校"
    return key


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


def _line(line_name: str) -> str:
    """「9号線千代田線」のような番号つきの正式名を、ふだんの呼び名（「千代田線」）にする。"""
    return re.sub(r"^\d+号線", "", line_name)
