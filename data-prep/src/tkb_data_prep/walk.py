"""道路距離の表（駅・バス停から歩いて行ける 100m マスと、その道のり）。

道のりは「マスの中心に一番近い道の点」から「駅・バス停の位置に一番近い道の点」までの、
歩ける道に沿った最短の長さ（メートル）。道の点は roads.SEGMENT_MAX_M ごとに足してあるので、
一番近い道の点を選ぶときの誤差は、その半分（20m）までになる。

一番近い道の点が SNAP_MAX_M より遠いマス・駅・バス停は、道でつながっていないものとして
表に入れない（山の中や海の上で、まわりに道がないマス）。

計算のしかた：駅（バス停）のまわりの、直線距離で上限の道のり以内にある道の点だけを取り出し、
その中で最短の道のりを計算する。道のりは直線距離より短くならないので、範囲の外の点を通る
道のりが上限より短くなることはない（取り出しても結果は変わらない）。
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from tkb_data_prep.roads import RoadGraph

# 一番近い道の点までの直線距離の上限（メートル）
SNAP_MAX_M = 200.0
# 平面に直すときの基準の緯度（1都3県の中ほど）。経度方向の長さの誤差は1都3県で1%ほどなので、
# 範囲を取り出すときだけ半径に余裕（RADIUS_MARGIN）を足す
REFERENCE_LAT = 35.6
METERS_PER_DEG_LAT = 110_950.0
RADIUS_MARGIN = 1.02


def to_plane(lat: npt.NDArray[np.float64], lon: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    x = lon * METERS_PER_DEG_LAT * np.cos(np.radians(REFERENCE_LAT))
    y = lat * METERS_PER_DEG_LAT
    return np.column_stack([x, y])


@dataclass(frozen=True)
class Snapped:
    """点ごとの、一番近い道の点の番号（道から遠すぎれば -1）。"""

    node: npt.NDArray[np.int64]

    @property
    def ok(self) -> npt.NDArray[np.bool_]:
        result: npt.NDArray[np.bool_] = self.node >= 0
        return result


class Walker:
    def __init__(self, roads: RoadGraph) -> None:
        self.roads = roads
        self.plane = to_plane(roads.lat, roads.lon)
        self.tree = cKDTree(self.plane)

    def snap(self, lat: npt.NDArray[np.float64], lon: npt.NDArray[np.float64]) -> Snapped:
        distance, node = self.tree.query(to_plane(lat, lon))
        node = np.where(distance <= SNAP_MAX_M * RADIUS_MARGIN, node, -1).astype(np.int64)
        return Snapped(node=node)

    def reach(
        self, source: int, limit: float
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
        """source から道のりが limit 以内の道の点（番号の昇順）と、その道のり。"""
        nearby = np.sort(
            np.asarray(
                self.tree.query_ball_point(self.plane[source], limit * RADIUS_MARGIN),
                dtype=np.int64,
            )
        )
        sub = self.roads.graph[nearby][:, nearby]
        start = int(np.searchsorted(nearby, source))
        distance = dijkstra(sub, directed=False, indices=start, limit=limit)
        within = np.isfinite(distance)
        return nearby[within], distance[within]

    def nearest(
        self, sources: npt.NDArray[np.int64], limit: float
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64]]:
        """道の点ごとに、一番近い source までの道のりとその source（届かなければ inf, -1）。"""
        distance, _, origin = dijkstra(
            self.roads.graph,
            directed=False,
            indices=np.unique(sources),
            limit=limit,
            min_only=True,
            return_predecessors=True,
        )
        return distance, origin.astype(np.int64)


class _CellIndex:
    """道の点から、その点を一番近い道の点とするマスを引く。"""

    def __init__(self, cells: Snapped) -> None:
        ok = np.flatnonzero(cells.ok)
        order = np.argsort(cells.node[ok], kind="stable")
        self.cells = ok[order]
        self.nodes = cells.node[ok][order]

    def cells_on(
        self, nodes: npt.NDArray[np.int64], distance: npt.NDArray[np.float64]
    ) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64]]:
        left = np.searchsorted(self.nodes, nodes, side="left")
        right = np.searchsorted(self.nodes, nodes, side="right")
        count = right - left
        hit = count > 0
        left, count, distance = left[hit], count[hit], distance[hit]
        offsets = np.repeat(left - (np.cumsum(count) - count), count) + np.arange(int(count.sum()))
        return self.cells[offsets], np.repeat(distance, count)


@dataclass(frozen=True)
class WalkTable:
    """（駅かバス停の番号, マスの番号, 道のり）の組。"""

    place: npt.NDArray[np.int32]
    cell: npt.NDArray[np.int32]
    distance: npt.NDArray[np.float32]


def walk_table(
    walker: Walker,
    places: Snapped,
    cells: Snapped,
    limit: float,
) -> WalkTable:
    """places（駅・バス停）ごとに、道のりが limit 以内のマス。"""
    index = _CellIndex(cells)
    by_source: dict[int, list[int]] = defaultdict(list)
    for place, node in enumerate(places.node.tolist()):
        if node >= 0:
            by_source[node].append(place)
    place_out: list[npt.NDArray[np.int32]] = []
    cell_out: list[npt.NDArray[np.int32]] = []
    dist_out: list[npt.NDArray[np.float32]] = []
    for source, place_indices in by_source.items():
        nodes, distance = walker.reach(source, limit)
        hit_cells, hit_dist = index.cells_on(nodes, distance)
        if hit_cells.shape[0] == 0:
            continue
        for place in place_indices:
            place_out.append(np.full(hit_cells.shape[0], place, dtype=np.int32))
            cell_out.append(hit_cells.astype(np.int32))
            dist_out.append(hit_dist.astype(np.float32))
    return WalkTable(
        place=_concat(place_out, np.int32),
        cell=_concat(cell_out, np.int32),
        distance=_concat(dist_out, np.float32),
    )


def _concat[T: np.generic](parts: Sequence[npt.NDArray[T]], dtype: type[T]) -> npt.NDArray[T]:
    if not parts:
        return np.empty(0, dtype=dtype)
    result: npt.NDArray[T] = np.concatenate(parts).astype(dtype)
    return result


def nearest_place(
    walker: Walker, places: Snapped, cells: Snapped, limit: float
) -> tuple[npt.NDArray[np.int32], npt.NDArray[np.float32]]:
    """マスごとに、道のりで一番近い place の番号と道のり（limit を超えれば -1, nan）。"""
    sources = places.node[places.ok]
    distance, origin = walker.nearest(sources, limit)
    place_of_node = dict(zip(places.node.tolist(), range(len(places.node)), strict=True))
    nearest = np.full(cells.node.shape[0], -1, dtype=np.int32)
    dist = np.full(cells.node.shape[0], np.nan, dtype=np.float32)
    ok = np.flatnonzero(cells.ok)
    node = cells.node[ok]
    reached = np.isfinite(distance[node])
    dist[ok[reached]] = distance[node[reached]]
    nearest[ok[reached]] = [place_of_node[int(o)] for o in origin[node[reached]].tolist()]
    return nearest, dist
