"""住まいの推定のテスト用の、小さな架空の地図（実際の人口ではない）（1km 四方、100m マス 100 個）。

- 500m メッシュ 4 つ（南西・南東・北西・北東）。20〜24歳は 25・50・75・100 人、総数はその4倍
- 町丁目：西半分（東西の番号 0〜4）が「文京区 弥生二丁目」、東半分が「文京区 根津一丁目」、
  北東の端の1列（東西の番号 9）だけ「中野区 弥生町一丁目」（名前に「弥生」を含む別の町）
- 駅：根津（千代田線）を東の端、東大前（南北線）を西の端に置く。道のりは直線距離で代える
- バス停：弥生二丁目（東京都）を真ん中に置く
- 小学校区：南半分が根津小学校
"""

import math

import numpy as np

from tkb_engine.scoring.tables import Places, ScoringTables, Towns, Walk, cell_code

MESHES = ["533946511", "533946512", "533946513", "533946514"]
LAT0 = 53 / 1.5 + 4 * 5 / 60 + 5 * 30 / 3600  # 1km メッシュ 53394651 の南の端
LON0 = 139 + 6 * 7.5 / 60 + 1 * 45 / 3600  # 同じく西の端
CELL_LAT = 3 / 3600
CELL_LON = 4.5 / 3600
STATIONS = {"根津": ("9号線千代田線", 9, 5), "東大前": ("7号線南北線", 0, 5)}
BUS = ("弥生二丁目", "東京都", 5, 5)


def meters(row_a: int, col_a: int, row_b: int, col_b: int) -> float:
    dy = (row_a - row_b) * CELL_LAT * 110_950
    dx = (col_a - col_b) * CELL_LON * 110_950 * math.cos(math.radians(LAT0))
    return math.hypot(dx, dy)


def walk(places: list[tuple[int, int]], rows: list[int], cols: list[int], limit: float) -> Walk:
    cell, dist, counts = [], [], []
    for row, col in places:
        count = 0
        for i, (r, c) in enumerate(zip(rows, cols, strict=True)):
            d = meters(r, c, row, col)
            if d <= limit:
                cell.append(i)
                dist.append(d)
                count += 1
        counts.append(count)
    return Walk(
        indptr=np.concatenate([[0], np.cumsum(counts)]).astype(np.int64),
        cell=np.asarray(cell, dtype=np.int32),
        distance=np.asarray(dist, dtype=np.float32),
    )


def build_tables() -> ScoringTables:
    rows: list[int] = []
    cols: list[int] = []
    for quadrant in range(4):
        for r in range(5 * (quadrant // 2), 5 * (quadrant // 2) + 5):
            for c in range(5 * (quadrant % 2), 5 * (quadrant % 2) + 5):
                rows.append(r)
                cols.append(c)
    lat = np.array([LAT0 + (r + 0.5) * CELL_LAT for r in rows])
    lon = np.array([LON0 + (c + 0.5) * CELL_LON for c in cols])
    station_places = [(row, col) for _, col, row in STATIONS.values()]
    nearest = [
        min(range(len(station_places)), key=lambda k: meters(r, c, *station_places[k]))
        for r, c in zip(rows, cols, strict=True)
    ]
    age = np.zeros((4, 20), dtype=np.float32)
    age[:, 4] = [25, 50, 75, 100]
    return ScoringTables(
        age=age,
        total=np.array([100, 200, 300, 400], dtype=np.float32),
        cell=np.array([cell_code(a, b) for a, b in zip(lat, lon, strict=True)], dtype=np.int64),
        lat=lat.astype(np.float32),
        lon=lon.astype(np.float32),
        mesh=np.repeat(np.arange(4, dtype=np.int32), 25),
        town=np.array([2 if c == 9 else (0 if c < 5 else 1) for c in cols], dtype=np.int32),
        school=np.array([0 if r < 5 else -1 for r in rows], dtype=np.int32),
        station=np.array(nearest, dtype=np.int32),
        station_m=np.array(
            [meters(r, c, *station_places[k]) for r, c, k in zip(rows, cols, nearest, strict=True)],
            dtype=np.float32,
        ),
        towns=Towns(
            key_code=["13105025002", "13105023001", "13114002001"],
            muni_code=["13105", "13105", "13114"],
            city=["文京区", "文京区", "中野区"],
            name=["弥生二丁目", "根津一丁目", "弥生町一丁目"],
            lat=np.array([LAT0 + 0.004] * 3),
            lon=np.array([LON0 + 0.002, LON0 + 0.009, LON0 + 0.012]),
        ),
        stations=Places(
            name=list(STATIONS),
            group=[line for line, _, _ in STATIONS.values()],
            lat=np.array([LAT0 + (row + 0.5) * CELL_LAT for _, _, row in STATIONS.values()]),
            lon=np.array([LON0 + (col + 0.5) * CELL_LON for _, col, _ in STATIONS.values()]),
        ),
        station_walk=walk(station_places, rows, cols, 800.0),
        bus_stops=Places(
            name=[BUS[0]],
            group=[BUS[1]],
            lat=np.array([LAT0 + 5.5 * CELL_LAT]),
            lon=np.array([LON0 + 5.5 * CELL_LON]),
        ),
        bus_walk=walk([(BUS[3], BUS[2])], rows, cols, 300.0),
        school_name=["根津小学校"],
        school_city=["文京区"],
    )
