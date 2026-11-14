"""層0：事前の人数（どこに、どんな人が住んでいるか）。

国勢調査の 500m メッシュの人口を、その中の 25 個の 100m マスに面積で均等に割る
（残る仮定：メッシュの中では人が均等に住んでいる）。年齢が推定されていればその5歳階級の人口、
なければ総人口を使う。
"""

import numpy as np
import numpy.typing as npt

from tkb_engine.scoring.constants import CELLS_PER_500M, YEARS_PER_AGE_CLASS
from tkb_engine.scoring.tables import AGE_CLASSES, ScoringTables


def age_class(age: int) -> int:
    """年齢の5歳階級の番号（0：0〜4歳 … 19：95歳以上）。"""
    if age < 0:
        raise ValueError("年齢が負です")
    return min(age // YEARS_PER_AGE_CLASS, AGE_CLASSES - 1)


def age_class_label(index: int) -> str:
    if index == AGE_CLASSES - 1:
        return "95歳以上"
    return f"{index * YEARS_PER_AGE_CLASS}〜{index * YEARS_PER_AGE_CLASS + 4}歳"


def prior(tables: ScoringTables, age: int | None) -> npt.NDArray[np.float64]:
    """100m マスごとの事前の人数。"""
    per_mesh = tables.total if age is None else tables.age[:, age_class(age)]
    result: npt.NDArray[np.float64] = per_mesh[tables.mesh].astype(np.float64) / CELLS_PER_500M
    return result
