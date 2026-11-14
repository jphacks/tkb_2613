"""100m マス（3次メッシュの 1/10 細分メッシュ）。

100m マスのコードは、1km メッシュ（8桁）のあとに南北の番号と東西の番号（0〜9）をつけた10桁。
500m メッシュ（9桁、末尾 1:南西 2:南東 3:北西 4:北東）は、ちょうど 5×5 の 100m マスでできている。
"""

import numpy as np
import numpy.typing as npt

# 1km メッシュの大きさ（度）：緯度 30 秒、経度 45 秒。100m マスはその 1/10
LAT_1KM = 30 / 3600
LON_1KM = 45 / 3600
CELLS_PER_500M = 25


def _corner_1km(code: str) -> tuple[float, float]:
    """1km メッシュの南西の角（緯度, 経度）。"""
    p, u = int(code[0:2]), int(code[2:4])
    q, v = int(code[4]), int(code[5])
    r, w = int(code[6]), int(code[7])
    lat = p / 1.5 + q * (5 / 60) + r * LAT_1KM
    lon = u + 100 + v * (7.5 / 60) + w * LON_1KM
    return lat, lon


def cells_of_500m(code: str) -> list[tuple[int, float, float]]:
    """500m メッシュの中の 25 個の 100m マス（コード, 中心の緯度, 中心の経度）。"""
    if len(code) != 9 or not code.isdigit() or code[8] not in "1234":
        raise ValueError(f"500m メッシュのコードではありません: {code}")
    lat0, lon0 = _corner_1km(code[:8])
    quadrant = int(code[8]) - 1
    row0 = 5 * (quadrant // 2)
    col0 = 5 * (quadrant % 2)
    cells: list[tuple[int, float, float]] = []
    for r in range(row0, row0 + 5):
        for c in range(col0, col0 + 5):
            cells.append(
                (
                    int(f"{code[:8]}{r}{c}"),
                    lat0 + (r + 0.5) * LAT_1KM / 10,
                    lon0 + (c + 0.5) * LON_1KM / 10,
                )
            )
    return cells


def grid(
    meshes_500m: list[str],
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """500m メッシュの並びの順に、100m マスのコード・緯度・経度を返す（各メッシュ 25 個ずつ）。"""
    codes = np.empty(len(meshes_500m) * CELLS_PER_500M, dtype=np.int64)
    lat = np.empty(codes.shape[0], dtype=np.float64)
    lon = np.empty(codes.shape[0], dtype=np.float64)
    for i, mesh in enumerate(meshes_500m):
        for j, (code, la, lo) in enumerate(cells_of_500m(mesh)):
            k = i * CELLS_PER_500M + j
            codes[k], lat[k], lon[k] = code, la, lo
    return codes, lat, lon
