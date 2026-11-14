"""W1 徒歩の距離：「家から駅まで徒歩4分」の本文と R1 の駅から、家がありうる範囲と世帯数。

- 半径：徒歩1分＝80m（不動産の表示に関する公正競争規約施行規則 第9条第9号「道路距離80メートル
  につき1分間を要するものとして算出」）。「徒歩4分」は道のり 320m 以内なので、直線ではそれより近い。
  よって駅を中心に半径 分×80m の円に入る
- 世帯数：令和2年国勢調査の地域メッシュ統計（500mメッシュ、data/processed の households_500m）。
  メッシュが円に一部だけかかるときは、メッシュの中で世帯が一様に分かれているとみなし、円と重なる
  面積の割合で按分する（中心だけで数えると、円より大きいメッシュを丸ごと足したり、まったく数えな
  かったりする）。面積は数値積分で、その誤差を見込んで 0.2% 引き、表示は有効数字2桁で切り捨てる
  （水増ししない）
- 駅の位置は stations 表の座標（路線ごとの行の平均）

本文は「家から〇〇駅まで徒歩N分」「最寄り駅まで徒歩N分」「〇〇駅から徒歩N分の部屋」の並びだけを
読む（1文の中で、家と駅の間の徒歩であること）。駅の名前が書いてあれば R1 の駅と同じであること。
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from tkb_common.schemas import Clue, ClueSource, Post
from tkb_engine.gazetteer import Gazetteer

METERS_PER_MINUTE = 80
MAX_MINUTES = 20
# 500m メッシュ（4次メッシュ、2分の1地域メッシュ）の大きさ（度）。緯度 15 秒、経度 22.5 秒
MESH_LAT = 15 / 3600
MESH_LON = 22.5 / 3600
# 円との重なりの面積を数値積分するときの、メッシュ1つあたりの帯の数。誤差は 0.1% 未満
SLICES = 2000
# 数値積分の誤差を見込んで、按分した世帯数から引く割合（水増ししないため）
INTEGRATION_MARGIN = 0.002

# 家と駅の間の徒歩の分数だけを読む。1文の中（句読点をまたがない）で、次のどれかの並びのとき：
#   「家から（根津）駅まで徒歩4分」「最寄り（の根津）駅まで徒歩4分」「（根津）駅から徒歩4分の部屋」
# 「実家」は本人の家ではないので除く。〇〇 は駅名で、R1 の駅と同じでなければ使わない
_CLAUSE = r"[^。、，,．.！!？?\n]{0,12}?"
_MINUTES = r"\s*徒歩\s*([0-9０-９]{1,2})\s*分"
WALK_PATTERNS = (
    re.compile(
        rf"(?:(?<!実)家|自宅|うち|部屋|アパート|マンション)から({_CLAUSE})駅(?:まで|へ)?(?:は)?{_MINUTES}"
    ),
    re.compile(rf"最寄り?(?:の)?({_CLAUSE})駅(?:まで|へ|から)?(?:は)?{_MINUTES}"),
    re.compile(rf"({_CLAUSE})駅(?:まで|から)?{_MINUTES}の(?:家|部屋|アパート|マンション|物件)"),
)

WALK_SOURCE = "徒歩1分＝80m（不動産の表示に関する公正競争規約施行規則 第9条第9号）"
CENSUS_SOURCE = "令和2年国勢調査 地域メッシュ統計（500mメッシュの世帯総数、e-Stat）"


@dataclass(frozen=True)
class MeshShare:
    code: str
    households: int
    share: float  # メッシュのうち円に入る面積の割合（0〜1）


@dataclass(frozen=True)
class WalkArea:
    station: str  # 「根津駅」
    minutes: int
    radius_m: int
    center: tuple[float, float]  # (緯度, 経度)
    meshes: tuple[MeshShare, ...]
    households: int  # 表示する世帯数（有効数字2桁で切り捨て）
    clue_indices: tuple[int, ...]

    @property
    def value(self) -> str:
        return (
            f"{self.station}から半径{self.radius_m}m（徒歩{self.minutes}分）、"
            f"約{self.households:,}世帯"
        )


def mesh_code(lat: float, lon: float) -> str:
    """緯度経度を含む 500m メッシュの番号（9桁）。"""
    p, a = divmod(lat * 60, 40)  # 1次：緯度 40 分
    q, b = divmod(a, 5)  # 2次：緯度 5 分
    r, c = divmod(b * 60, 30)  # 3次：緯度 30 秒
    s = int(c >= 15)
    lon_rest = lon - 100
    u, f = divmod(lon_rest, 1)
    v, g = divmod(f * 60, 7.5)
    w, h = divmod(g * 60, 45)
    t = int(h >= 22.5)
    return f"{int(p):02d}{int(u):02d}{int(q)}{int(v)}{int(r)}{int(w)}{s * 2 + t + 1}"


def mesh_bounds(code: str) -> tuple[float, float, float, float]:
    """500m メッシュの (南, 西, 北, 東)。"""
    lat = int(code[0:2]) / 1.5 + int(code[4]) * 5 / 60 + int(code[6]) * 30 / 3600
    lon = int(code[2:4]) + 100 + int(code[5]) * 7.5 / 60 + int(code[7]) * 45 / 3600
    quarter = int(code[8]) - 1
    lat += (quarter // 2) * MESH_LAT
    lon += (quarter % 2) * MESH_LON
    return lat, lon, lat + MESH_LAT, lon + MESH_LON


def meters_per_degree(lat: float) -> tuple[float, float]:
    """その緯度での、緯度1度・経度1度の長さ（m）。"""
    phi = math.radians(lat)
    per_lat = 111_132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
    per_lon = 111_412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)
    return per_lat, per_lon


def circle_shares(
    households: dict[str, int], center: tuple[float, float], radius_m: float
) -> list[MeshShare]:
    """円にかかる 500m メッシュと、円に入る面積の割合。世帯のないメッシュは入れない。"""
    lat0, lon0 = center
    per_lat, per_lon = meters_per_degree(lat0)
    dlat, dlon = radius_m / per_lat, radius_m / per_lon
    codes = {
        mesh_code(lat0 + i * MESH_LAT / 2, lon0 + j * MESH_LON / 2)
        for i in range(-math.ceil(2 * dlat / MESH_LAT) - 1, math.ceil(2 * dlat / MESH_LAT) + 2)
        for j in range(-math.ceil(2 * dlon / MESH_LON) - 1, math.ceil(2 * dlon / MESH_LON) + 2)
    }
    shares = []
    for code in sorted(codes):
        if code not in households:
            continue
        share = _inside_share(mesh_bounds(code), center, radius_m, per_lat, per_lon)
        if share > 0:
            shares.append(MeshShare(code, households[code], share))
    return shares


def _inside_share(
    bounds: tuple[float, float, float, float],
    center: tuple[float, float],
    radius_m: float,
    per_lat: float,
    per_lon: float,
) -> float:
    """メッシュのうち円に入る面積の割合。東西に細い帯に分け、帯ごとに円の弦と南北の範囲が重なる長さを足す。"""
    south, west, north, east = bounds
    y1, y2 = (south - center[0]) * per_lat, (north - center[0]) * per_lat
    x1, x2 = (west - center[1]) * per_lon, (east - center[1]) * per_lon
    width = (x2 - x1) / SLICES
    area = 0.0
    for i in range(SLICES):
        x = x1 + (i + 0.5) * width
        if abs(x) >= radius_m:
            continue
        half = math.sqrt(radius_m * radius_m - x * x)
        area += max(0.0, min(y2, half) - max(y1, -half)) * width
    return area / ((x2 - x1) * (y2 - y1))


def floor_two_digits(value: float) -> int:
    """有効数字2桁で切り捨て（1,234 → 1,200、87.9 → 87）。"""
    n = int(value)
    if n < 100:
        return n
    unit = int(10 ** (len(str(n)) - 2))
    return n // unit * unit


def walk_area(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    station_value: str,
    station_clue_indices: Sequence[int],
    gaz: Gazetteer,
) -> WalkArea | None:
    """A supported station candidate and a walk post yield the home_walk_area value."""
    if not station_value or not gaz.households:
        return None
    name = station_value.removesuffix("駅")
    center = gaz.station_point(name)
    if center is None:
        return None
    for post in posts:
        minutes = _walk_minutes(post.text, name)
        if minutes is None:
            continue
        evidence = [
            i
            for i, c in enumerate(clues)
            if c.post_id == post.post_id and c.source in {ClueSource.TEXT, ClueSource.META}
        ]
        if not evidence:
            continue
        radius = minutes * METERS_PER_MINUTE
        meshes = circle_shares(gaz.households, center, radius)
        total = sum(m.households * m.share for m in meshes) * (1 - INTEGRATION_MARGIN)
        return WalkArea(
            station=f"{name}駅",
            minutes=minutes,
            radius_m=radius,
            center=center,
            meshes=tuple(meshes),
            households=floor_two_digits(total),
            clue_indices=tuple(sorted({*station_clue_indices, *evidence})),
        )
    return None


def _walk_minutes(text: str, station: str) -> int | None:
    """家から駅までの徒歩の分数。WALK_PATTERNS の並びでなければ None。"""
    for pattern in WALK_PATTERNS:
        for m in pattern.finditer(text):
            # 駅の名前が書いてあれば R1 の駅と同じこと（「の」や「根津の」の形も受け付ける）
            name = m[1].strip().removeprefix("の").removesuffix("の")
            if name and not name.endswith(station):
                continue
            minutes = int(m[2].translate(str.maketrans("０１２３４５６７８９", "0123456789")))
            if 1 <= minutes <= MAX_MINUTES:
                return minutes
    return None
