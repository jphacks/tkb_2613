"""OpenStreetMap の道路網から、歩ける道のグラフを作る。

入力は Geofabrik の関東の抜粋（data-prep/raw/osm/kanto-latest.osm.pbf、ODbL）。
1都3県を囲む範囲の中の、歩ける道（highway の種類で選ぶ）だけを使う。

- 点（node）は道の曲がり角・交差点。長い区間は SEGMENT_MAX_M ごとに点を足して分ける
  （マスの中心や駅に一番近い道の点を、点の中から選ぶため。足した点の間隔が誤差の上限になる）
- 辺の長さは2点の間の大圏距離（メートル）。一方通行は歩く人には関係ないので、向きは持たない

できたグラフは raw/osm/ の下に .npz で置き、次からはそれを読む（pbf が変わったら作り直す）。
"""

from array import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import osmium
from scipy.sparse import csr_matrix

from tkb_data_prep.errors import DataPrepError

# 1都3県を囲む範囲（島しょ部は含めない）。この外の点しか持たない区間は捨てる
BBOX_SOUTH, BBOX_NORTH = 34.85, 36.30
BBOX_WEST, BBOX_EAST = 138.90, 140.90

# 歩ける道の種類。高速道路（motorway）と、工事中・計画中の道は使わない
WALKABLE_HIGHWAYS = frozenset(
    {
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "road",
        "pedestrian",
        "footway",
        "path",
        "steps",
        "track",
        "cycleway",
        "corridor",
    }
)
# 歩行者が通れないと書かれた道
NO_FOOT = frozenset({"no"})
NO_ACCESS = frozenset({"no"})
FOOT_ALLOWED = frozenset({"yes", "designated", "permissive"})

# 長い区間を分ける長さ（メートル）。マスや駅を道に寄せるときの誤差は、この半分まで
SEGMENT_MAX_M = 40.0
EARTH_RADIUS_M = 6_371_008.8
CACHE_VERSION = 1


@dataclass(frozen=True)
class RoadGraph:
    """歩ける道のグラフ。lat・lon は点ごと、graph は点と点の距離（メートル、両向き）。"""

    lat: npt.NDArray[np.float64]
    lon: npt.NDArray[np.float64]
    graph: csr_matrix

    @property
    def size(self) -> int:
        return int(self.lat.shape[0])


def walkable(tags: osmium.osm.TagList) -> bool:
    if tags.get("highway") not in WALKABLE_HIGHWAYS:
        return False
    foot = tags.get("foot")
    if foot in NO_FOOT:
        return False
    if tags.get("area") == "yes":
        return False
    return not (tags.get("access") in NO_ACCESS and foot not in FOOT_ALLOWED)


def _in_bbox(lat: float, lon: float) -> bool:
    return BBOX_SOUTH <= lat <= BBOX_NORTH and BBOX_WEST <= lon <= BBOX_EAST


class _Collector:
    """道に出てくる点を、出てきた順にためる。

    同じ点が何本もの道に出てくるので、OSM の ID で重複を除くのは最後に numpy で行う
    （関東全体では点が数千万になり、Python の辞書では本番の機械のメモリに載らないため）。
    位置は 1e-7 度単位の整数（OSM の内部の表し方と同じ）で持つ。
    """

    def __init__(self) -> None:
        self.ids = array("q")
        self.x = array("i")
        self.y = array("i")
        # 1 なら、ひとつ前の点とこの点の間が道でつながっている
        self.joined = bytearray()

    def add_way(self, refs: list[tuple[int, int, int]]) -> None:
        previous_kept = False
        for osm_id, x, y in refs:
            if not _in_bbox(y / 1e7, x / 1e7):
                previous_kept = False
                continue
            self.ids.append(osm_id)
            self.x.append(x)
            self.y.append(y)
            self.joined.append(1 if previous_kept else 0)
            previous_kept = True


def read_pbf(pbf: Path, index_dir: Path) -> RoadGraph:
    """pbf から歩ける道のグラフを作る。点の位置の索引は index_dir の下のファイルに置く。"""
    if not pbf.is_file():
        raise DataPrepError(f"{pbf} がありません。data-prep/README.md の手順で置いてください")
    index_dir.mkdir(parents=True, exist_ok=True)
    index_file = index_dir / "node-locations.idx"
    collector = _Collector()
    processor = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations(f"sparse_file_array,{index_file}")
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    try:
        for way in processor:
            if isinstance(way, osmium.osm.Way) and walkable(way.tags):
                collector.add_way([(r.ref, r.x, r.y) for r in way.nodes if r.location.valid()])
    finally:
        index_file.unlink(missing_ok=True)
    return build_graph(
        np.frombuffer(collector.ids, dtype=np.int64),
        np.frombuffer(collector.x, dtype=np.int32),
        np.frombuffer(collector.y, dtype=np.int32),
        np.frombuffer(collector.joined, dtype=np.uint8).astype(bool),
    )


def build_graph(
    ids: npt.NDArray[np.int64],
    x: npt.NDArray[np.int32],
    y: npt.NDArray[np.int32],
    joined: npt.NDArray[np.bool_],
) -> RoadGraph:
    """出てきた順の点（ID・位置・前の点とつながっているか）からグラフを作る。"""
    unique, first, inverse = np.unique(ids, return_index=True, return_inverse=True)
    lat = y[first].astype(np.float64) / 1e7
    lon = x[first].astype(np.float64) / 1e7
    ends = np.flatnonzero(joined)
    a = inverse[ends - 1]
    b = inverse[ends]
    distinct = a != b
    a, b = a[distinct], b[distinct]
    return _densified(lat, lon, a, b, int(unique.shape[0]))


def _densified(
    lat: npt.NDArray[np.float64],
    lon: npt.NDArray[np.float64],
    a: npt.NDArray[np.int64],
    b: npt.NDArray[np.int64],
    n: int,
) -> RoadGraph:
    """SEGMENT_MAX_M より長い区間に、等間隔で点を足して分ける。"""
    length = haversine_array(lat[a], lon[a], lat[b], lon[b])
    pieces = np.maximum(1, np.ceil(length / SEGMENT_MAX_M)).astype(np.int64)
    extra = pieces - 1
    total_extra = int(extra.sum())
    # 区間ごとに、足す点の番号（n から順に）と、区間の中での位置 t
    seg_of_extra = np.repeat(np.arange(a.shape[0]), extra)
    starts = np.cumsum(extra) - extra
    k = np.arange(total_extra) - starts[seg_of_extra] + 1
    t = k / pieces[seg_of_extra]
    new_lat = lat[a[seg_of_extra]] + (lat[b[seg_of_extra]] - lat[a[seg_of_extra]]) * t
    new_lon = lon[a[seg_of_extra]] + (lon[b[seg_of_extra]] - lon[a[seg_of_extra]]) * t
    new_ids = n + np.arange(total_extra)
    # 区間の点の並び：a, 足した点..., b
    chain_start = np.where(extra > 0, n + starts, b)
    piece_len = length / pieces
    src = [a]
    dst = [chain_start]
    lengths = [piece_len]
    # 足した点から次の点へ（最後の足した点は b へ）
    is_last = k == extra[seg_of_extra]
    src.append(new_ids)
    dst.append(np.where(is_last, b[seg_of_extra], new_ids + 1))
    lengths.append(piece_len[seg_of_extra])
    rows = np.concatenate(src)
    cols = np.concatenate(dst)
    data = np.concatenate(lengths)
    all_lat = np.concatenate([lat, new_lat])
    all_lon = np.concatenate([lon, new_lon])
    return RoadGraph(lat=all_lat, lon=all_lon, graph=_symmetric(rows, cols, data, n + total_extra))


def _symmetric(
    rows: npt.NDArray[np.int64],
    cols: npt.NDArray[np.int64],
    data: npt.NDArray[np.float64],
    n: int,
) -> csr_matrix:
    """両向きの辺にする。同じ2点を結ぶ辺が2つ以上あれば、短いほうを使う。"""
    r = np.concatenate([rows, cols])
    c = np.concatenate([cols, rows])
    d = np.concatenate([data, data])
    order = np.lexsort((d, c, r))
    r, c, d = r[order], c[order], d[order]
    keep = np.ones(r.shape[0], dtype=bool)
    keep[1:] = (r[1:] != r[:-1]) | (c[1:] != c[:-1])
    return csr_matrix((d[keep], (r[keep], c[keep])), shape=(n, n))


def haversine_array(
    lat1: npt.NDArray[np.float64],
    lon1: npt.NDArray[np.float64],
    lat2: npt.NDArray[np.float64],
    lon2: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    result: npt.NDArray[np.float64] = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(h))
    return result


def load(pbf: Path, cache: Path) -> RoadGraph:
    """cache が pbf と同じ版から作られていれば読み、そうでなければ作り直して書く。"""
    stamp = _stamp(pbf)
    if cache.is_file():
        with np.load(cache) as saved:
            if str(saved["stamp"]) == stamp:
                graph = csr_matrix(
                    (saved["data"], saved["indices"], saved["indptr"]),
                    shape=(saved["lat"].shape[0], saved["lat"].shape[0]),
                )
                return RoadGraph(lat=saved["lat"], lon=saved["lon"], graph=graph)
    roads = read_pbf(pbf, cache.parent)
    np.savez(
        cache,
        stamp=np.array(stamp),
        lat=roads.lat,
        lon=roads.lon,
        data=roads.graph.data,
        indices=roads.graph.indices,
        indptr=roads.graph.indptr,
    )
    return roads


def _stamp(pbf: Path) -> str:
    if not pbf.is_file():
        raise DataPrepError(f"{pbf} がありません。data-prep/README.md の手順で置いてください")
    stat = pbf.stat()
    return f"v{CACHE_VERSION}:{stat.st_size}:{int(stat.st_mtime)}:{SEGMENT_MAX_M}"
