"""住まいの推定（点数の地図）を fixture で評価し、Markdown の表で出す。

uv run python eval/scoring_eval.py eval/local/demo_student_scoring.json
uv run python eval/scoring_eval.py eval/local/demo_student_scoring.json --home 35.71625,139.76312

表（data/processed/scoring_*.parquet）は make data で作る。
fixture の home（緯度・経度）が本当の自宅。
"""

import argparse
import json
import time
from pathlib import Path

from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import DATA_DIR, Knowledge
from tkb_engine.scoring import tables as scoring_tables
from tkb_engine.scoring.estimate import Estimate, Region, describe_cell, estimate, rank_percent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--home", help="本当の自宅（緯度,経度）。省略すると fixture の home")
    parser.add_argument("--data", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    doc = json.loads(args.fixture.read_text(encoding="utf-8"))
    posts = [Post.model_validate(p) for p in doc["posts"]]
    clues = [Clue.model_validate(c) for c in doc["clues"]]
    lat, lon = (
        (float(v) for v in args.home.split(","))
        if args.home
        else (doc["home"]["lat"], doc["home"]["lon"])
    )
    tables = scoring_tables.load(args.data)
    if tables is None:
        print("住まいの推定の表がありません。make data を実行してください")
        return 1
    home = tables.cell_of(lat, lon)
    if home is None:
        print("自宅の点が表のマスにありません")
        return 1

    started = time.perf_counter()
    result = estimate(posts, clues, tables, Knowledge.load().collection_areas)
    seconds = time.perf_counter() - started
    if result is None:
        print("場所のシグナルがありません")
        return 1
    text = {p.post_id: p.text for p in posts}
    report(result, tables, home, text, seconds)
    return 0


def people(region: Region) -> str:
    return f"{region.people:,.0f}"


def report(
    result: Estimate,
    tables: scoring_tables.ScoringTables,
    home: int,
    text: dict[str, str],
    seconds: float,
) -> None:
    print(f"自宅のマス：{int(tables.cell[home])}（{describe_cell(tables, home)}）\n")
    print("## 投稿を1件ずつ重ねたときの 8割の範囲\n")
    print("| 順 | 投稿 | 層 | 8割の範囲の人数 | 範囲のマス | 同じ誕生日の計算上の人数 |")
    print("|---|---|---|---|---|---|")
    layers: dict[str, list[str]] = {}
    for e in result.evidence:
        mark = f"{e.signal.layer}" if e.applied else f"{e.signal.layer}（使えず）"
        layers.setdefault(e.signal.post_id, []).append(f"{mark}:{e.signal.value}")
    for i, (post_id, region) in enumerate(result.steps):
        label = text[post_id] if post_id else "（投稿なし：事前の人数だけ）"
        same = "" if region.same_birthday is None else f"{region.same_birthday:.2f}"
        used = "、".join(layers.get(post_id, [])) if post_id else "0"
        print(f"| {i} | {label} | {used} | {people(region)} | {region.cells:,} | {same} |")

    print("\n## 投稿ごとの影響（その投稿だけを外したとき）\n")
    print("| 投稿 | 外したときの人数 | 増え方 | 印 |")
    print("|---|---|---|---|")
    ranked = sorted(result.without.items(), key=lambda kv: -kv[1].people)
    for i, (post_id, region) in enumerate(ranked):
        delta = region.people - result.region.people
        mark = (
            "消すべき1件"
            if i == 0 and delta > 0
            else ("ほかと矛盾している可能性" if delta < 0 else "")
        )
        print(f"| {text[post_id]} | {people(region)} | {delta:+,.0f} | {mark} |")

    rank, percent = rank_percent(result.probability, home)
    print("\n## 本当の自宅の順位と、層7を掛けた場合\n")
    print("| | 8割の範囲の人数 | 範囲のマス | 自宅の順位 | 上位 | 一番濃いマス |")
    print("|---|---|---|---|---|---|")
    top = describe_cell(tables, result.region.top_cell)
    print(
        f"| 層7を掛けない（本計算） | {people(result.region)} | {result.region.cells:,} | "
        f"{rank:,} / {tables.size:,} | {percent:.4f}% | {top} |"
    )
    if result.with_geoprofile is not None:
        p7, region7 = result.with_geoprofile
        rank7, percent7 = rank_percent(p7, home)
        top7 = describe_cell(tables, region7.top_cell)
        print(
            f"| 層7を掛ける | {people(region7)} | {region7.cells:,} | "
            f"{rank7:,} / {tables.size:,} | {percent7:.4f}% | {top7} |"
        )
    if result.geoprofile is not None:
        kept = "、".join(p.name for p in result.geoprofile.places)
        other = "、".join(p.name for p in result.geoprofile.other_bases) or "なし"
        buffer_m = result.geoprofile.buffer_m
        print(f"\n層7の場所：{kept}（もう1つの拠点：{other}、緩衝地帯 {buffer_m:.0f}m）")
    print(f"\n層8：年齢 {result.age}、誕生日 {result.birthday}、")
    same = result.region.same_birthday
    print(
        f"同じ年齢・同じ誕生日の計算上の人数（目安） {same:.3f} 人" if same is not None else "なし"
    )
    print(f"\n1回の診断（estimate）にかかった時間：{seconds:.2f} 秒")


if __name__ == "__main__":
    raise SystemExit(main())
