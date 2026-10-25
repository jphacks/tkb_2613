"""data-prep の表（stations・postal・muni_mesh）と、手がかりの値の引き当て。

表は `make data` で data/processed/ に作る（コミットしない）。
テストでは Gazetteer を直接組み立てる。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from tkb_common.schemas import Clue, ClueType

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processed"
# 「線」だけや1文字の路線名で、関係のない文字に合わないようにする
MIN_LINE_NAME_LENGTH = 3


@dataclass(frozen=True)
class Gazetteer:
    """推理ルールが引く表。

    - stations：駅ごとに {"station_name", "mesh_1km", "line_name", ...}（駅と路線の組ごとに1行）
    - postal：郵便番号ごとに {"postal_code"（ハイフンなし7桁）, "muni_code", "city", "town", ...}
    - muni_meshes：区市町村コード → その区市町村にかかる 1km メッシュの集合
    """

    stations: list[dict[str, str]] = field(default_factory=list)
    postal: list[dict[str, str]] = field(default_factory=list)
    muni_meshes: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Gazetteer":
        meshes: dict[str, set[str]] = {}
        for row in pq.read_table(data_dir / "muni_mesh.parquet").to_pylist():
            meshes.setdefault(row["muni_code"], set()).add(row["mesh_1km"])
        return cls(
            stations=pq.read_table(data_dir / "stations.parquet").to_pylist(),
            postal=pq.read_table(data_dir / "postal.parquet").to_pylist(),
            muni_meshes=meshes,
        )

    def station_names(self, value: str) -> set[str]:
        """駅名の手がかり（「根x」「根津駅」など）に合う駅名。"""
        pattern = _pattern(value.strip().removesuffix("駅"))
        return {s["station_name"] for s in self.stations if pattern.fullmatch(s["station_name"])}

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


def _pattern(value: str) -> re.Pattern[str]:
    """読めない文字の x を1文字として扱う。"""
    return re.compile("".join("." if ch == "x" else re.escape(ch) for ch in value))


def _town(town: str) -> str:
    """「弥生（次のビルを除く）」のような括弧書きを落とす。"""
    return re.sub(r"（.*）$", "", town)


def _line(line_name: str) -> str:
    """「9号線千代田線」のような番号つきの正式名を、ふだんの呼び名（「千代田線」）にする。"""
    return re.sub(r"^\d+号線", "", line_name)
