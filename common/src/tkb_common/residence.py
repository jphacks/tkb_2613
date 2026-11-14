"""住まいの推定（点数の地図）の結果の形。Python 側の正。

web/src/types/residence.ts と同時に変更すること。
契約は docs/api-sse-contract.md の「住まいの推定」。
数字は「推定」で、画面では「確定」「特定した」と言わず、相対的な言い方にする。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResidenceRegion(BaseModel):
    """8割の範囲（確率の高い順に足して8割に届くまでのマス）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    people: float = Field(ge=0)  # 範囲に住む人数（age_class があればその5歳階級）
    cells: int = Field(ge=1)  # 範囲の 100m マスの数
    city: str | None  # 一番濃いマスの市区町村
    town: str | None  # 一番濃いマスの町丁目
    station: str | None  # 一番濃いマスから道のりで一番近い駅
    station_walk_minutes: int | None
    # 層8：同じ年齢・同じ誕生日の計算上の人数（目安）。年齢と誕生日がそろったときだけ
    same_birthday: float | None


class ResidenceMapCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lat: float  # マスの中心
    lon: float
    p: float = Field(ge=0)  # そのマスに住んでいる確率（本計算。層7は掛けない）
    p_geo: float = Field(ge=0)  # 層7を掛けたときの確率
    geo: float = Field(ge=0, le=1)  # 層7だけの点数（一番高いマスが 1）。層7がなければ 0
    in_region: bool  # 本計算の 8割の範囲に入るか


class ResidenceMapLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["station", "town"]
    name: str
    lat: float
    lon: float


class ResidenceMap(BaseModel):
    """一番濃いマスのまわり（東西南北それぞれ 1.5km まで）のマス。外部の地図タイルは使わない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell_lat: float  # マスの大きさ（度）
    cell_lon: float
    cells: list[ResidenceMapCell]
    labels: list[ResidenceMapLabel]


class ResidenceStep(BaseModel):
    """投稿を1件ずつ重ねたとき（投稿の時刻の順）。最初の行は投稿なし（post_id が null）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str | None
    people: float = Field(ge=0)
    cells: int = Field(ge=1)
    same_birthday: float | None


class ResidenceInfluence(BaseModel):
    """その投稿だけを外したときの 8割の範囲。delta が一番大きい投稿が「消すべき1件」。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str
    people_without: float = Field(ge=0)
    delta: float  # 外したときの人数 − 今の人数
    contradiction: bool  # 外すと範囲が狭まる（ほかと矛盾している可能性）


class ResidenceEvidence(BaseModel):
    """推定に使った材料。layer は設計書の層の番号（0：年齢、1〜7、8：誕生日）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str
    layer: int = Field(ge=0, le=8)
    kind: str
    value: str
    excerpt: str
    applied: bool  # 表で重みが決まったか（表にない路線名などは false で、掛けていない）
    clue_indices: list[int]  # 写真の手がかりの番号（診断の clues での番号）。本文なら空


class ResidenceGeoprofile(BaseModel):
    """層7（よく行く場所、Rossmo の CGT）を掛けた結果。参考の層。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    region: ResidenceRegion
    places: list[str]
    other_bases: list[str]  # ほかから大きく離れた「もう1つの拠点」として外した場所
    buffer_m: float


class ResidenceEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    age_class: str | None  # 例：「20〜24歳」。年齢がわからなければ null（総人口で数える）
    region: ResidenceRegion
    geoprofile: ResidenceGeoprofile | None
    map: ResidenceMap
    steps: list[ResidenceStep]
    influence: list[ResidenceInfluence]  # delta の大きい順
    evidence: list[ResidenceEvidence]
    assumptions: list[str]
    sources: list[str]
