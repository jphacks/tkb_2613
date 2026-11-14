"""f1 絞り込みの演出に渡すデータ。1都3県 → 生活圏（W1 の範囲）→ 番地（R6、区画）。

画面はメッシュ番号から位置を計算して四角いマスを描く。数は次のとおり。
- 1都3県：households_500m の世帯数の合計。県境のメッシュには隣の県の世帯も少し入るので、
  画面では10万世帯単位で切り捨てて「約」を付ける
- 生活圏：W1 の世帯数（円と重なる面積で按分し、有効数字2桁で切り捨て）
- 番地：数ではなく「1区画」

各段の post_ids は、その段の推定の根拠の投稿。画面は仮除外した投稿を含む段を出さない。
推定の段（生活圏・番地）がどちらもなければ None。
"""

from collections.abc import Sequence
from functools import cache
from typing import Any

from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import Conclusion
from tkb_engine.walk_area import CENSUS_SOURCE, WALK_SOURCE, mesh_bounds, walk_area

REGION_LABEL = "1都3県"


def narrowing(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    conclusions: Sequence[Conclusion],
    gaz: Gazetteer,
) -> dict[str, Any] | None:
    if not gaz.households:
        return None
    area = walk_area(clues, posts, conclusions, gaz)
    block = next((c for c in conclusions if c.rule == "R6" and c.attribute == "home_block"), None)
    if area is None and block is None:
        return None
    south, west, north, east = _region_bounds(tuple(sorted(gaz.households)))
    return {
        "region": {
            "label": REGION_LABEL,
            "households": sum(gaz.households.values()),
            "bounds": [south, west, north, east],
        },
        "walk": None
        if area is None
        else {
            "station": area.station,
            "minutes": area.minutes,
            "radius_m": area.radius_m,
            "center": list(area.center),
            "households": area.households,
            "meshes": [
                {"code": m.code, "households": m.households, "share": round(m.share, 3)}
                for m in area.meshes
            ],
            "post_ids": _post_ids(clues, area.clue_indices),
        },
        "block": None
        if block is None
        else {"value": block.value, "post_ids": _post_ids(clues, block.clue_indices)},
        "sources": [CENSUS_SOURCE, *([WALK_SOURCE] if area else [])],
    }


def _post_ids(clues: Sequence[Clue], indices: Sequence[int]) -> list[str]:
    return list(dict.fromkeys(clues[i].post_id for i in indices))


@cache
def _region_bounds(codes: tuple[str, ...]) -> tuple[float, float, float, float]:
    """世帯のあるメッシュ全体の (南, 西, 北, 東)。"""
    boxes = [mesh_bounds(c) for c in codes]
    return (
        round(min(b[0] for b in boxes), 6),
        round(min(b[1] for b in boxes), 6),
        round(max(b[2] for b in boxes), 6),
        round(max(b[3] for b in boxes), 6),
    )
