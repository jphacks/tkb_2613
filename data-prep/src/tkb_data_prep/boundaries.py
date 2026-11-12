"""区市町村の境界（国土数値情報「行政区域（N03）」2026年1月1日時点）で、点がどの区市町村にあるかを引く。

入力は都道府県ごとの N03-20260101_{11..14}_GML.zip に入っている GeoJSON（JGD2011 経緯度、
MultiPolygon）。N03_007 が全国地方公共団体コード（政令市は区のコード）。コードのない
「所属未定地」は使わない。多角形の処理には shapely を使う（data-prep だけの依存）。
engine には多角形を渡さず、変換済みの表（バス停の区市町村など）だけを渡す。
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from tkb_data_prep.config import PREFECTURES, Paths
from tkb_data_prep.io import read_zip_member


@dataclass(frozen=True)
class Locator:
    tree: STRtree
    codes: tuple[str, ...]

    @classmethod
    def from_geojson(cls, docs: Iterable[dict[str, Any]]) -> "Locator":
        geometries = []
        codes = []
        for doc in docs:
            for feature in doc.get("features", []):
                code = (feature.get("properties") or {}).get("N03_007")
                if not code:
                    continue
                geometries.append(shape(feature["geometry"]))
                codes.append(str(code))
        return cls(STRtree(geometries), tuple(codes))

    def locate(self, lat: float, lon: float) -> str | None:
        """点を含む区市町村のコード。どこにも入らないか、2つ以上に入れば None。"""
        point = shapely.Point(lon, lat)
        found = {self.codes[i] for i in self.tree.query(point, predicate="intersects")}
        return next(iter(found)) if len(found) == 1 else None


def load(paths: Paths) -> Locator | None:
    """zip が1つもなければ None（境界なしで続ける）。"""
    docs = [
        json.loads(read_zip_member(path, ".geojson").decode("utf-8"))
        for pref in PREFECTURES
        if (path := paths.ksj_boundary_zip(pref)).is_file()
    ]
    return Locator.from_geojson(docs) if docs else None
