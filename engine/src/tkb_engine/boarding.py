"""搭乗券のバーコードを使う推理ルール BP1・BP2。

- BP1 搭乗券：写真の code の手がかりを IATA の搭乗券（BCBP）として読み（tkb_common.bcbp）、
  氏名（ローマ字、full_name）と、搭乗日・出発地・到着地から留守の予定（long_term_home_absence）。
  搭乗日は年の通算日なので、年は投稿日から決め、投稿日より前になるなら翌年にする。ただし翌年に
  回すのは投稿から ROLLOVER_MAX_DAYS 日以内（年末の投稿で年始の便）だけで、それ以外は搭乗後に
  上げた搭乗券とみなし、留守の予定にしない。
  「帰ってきた」など終わった旅行の投稿の搭乗券は、留守の予定にしない（氏名は使う）。
  予約番号は値にもメモにも出さず、「予約番号も読み取れる」とだけ書く（detect が伏せてある）
- BP2 住所と留守：家の場所（R6 の番地、なければ R1 の町名・最寄り駅）と、別の投稿の留守の予定
  （BP1 の搭乗券、なければ X3 の旅行・帰省の本文）から、「〇〇付近の家が、△月△日に留守になる」。
  根拠には両方の投稿を入れる。R1 と X3 の組み合わせは X3 と同じなので出さない。
  BP2 が出たら、X3 と BP1 の留守の予定は BP2 に置き換える（links.link）
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from tkb_common.bcbp import BoardingPass, parse_code_value
from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.rules import Conclusion, _local

# 主な空港コードの名前。ほかはコードのまま出す
AIRPORTS = {
    "HND": "東京（羽田）",
    "NRT": "東京（成田）",
    "CTS": "札幌（新千歳）",
    "HKD": "函館",
    "AOJ": "青森",
    "SDJ": "仙台",
    "KIJ": "新潟",
    "KMQ": "小松",
    "NGO": "名古屋（中部）",
    "ITM": "大阪（伊丹）",
    "KIX": "大阪（関西）",
    "UKB": "神戸",
    "OKJ": "岡山",
    "HIJ": "広島",
    "TAK": "高松",
    "MYJ": "松山",
    "FUK": "福岡",
    "NGS": "長崎",
    "KMJ": "熊本",
    "OIT": "大分",
    "KMI": "宮崎",
    "KOJ": "鹿児島",
    "OKA": "那覇",
}
# 終わった旅行の話の言葉。X3（links.py）も使う。この投稿の搭乗券は留守の予定にしない
PAST_WORDS = ("行ってきた", "帰ってきた", "ただいま", "帰宅した", "楽しかった")
# 投稿日より前の通算日を翌年の便とみなす上限（日）。搭乗券は出発の少し前に出るものなので、
# これより先になるなら終わった便の搭乗券とみなす
ROLLOVER_MAX_DAYS = 60
PNR_NOTE = "予約番号も読み取れる（推定には使わず、表示もしない）"
# BP2 で家の場所に使う結論の項目。前ほど細かい
HOME_ATTRIBUTES = ("home_block", "home_area", "station")


@dataclass(frozen=True)
class Plan:
    """留守の予定。when は「11月1日に」「来週（10月26日の週）から4日ほど」の形。"""

    when: str
    clue_indices: tuple[int, ...]
    source: str
    from_boarding_pass: bool


def airport(code: str) -> str:
    return AIRPORTS.get(code, code)


def boarding_passes(
    clues: Sequence[Clue], posts: Sequence[Post]
) -> list[tuple[int, BoardingPass, Post]]:
    """写真の code の手がかりのうち、搭乗券として読めたもの（手がかりの番号・中身・投稿）。"""
    by_id = {p.post_id: p for p in posts}
    found = []
    for i, c in enumerate(clues):
        if c.type is not ClueType.CODE or c.image_index is None or c.post_id not in by_id:
            continue
        if (bp := parse_code_value(c.value)) is not None:
            found.append((i, bp, by_id[c.post_id]))
    return found


def flight_date(julian_day: int, posted: date) -> date | None:
    """年の通算日を日付にする。投稿日より前なら翌年（投稿から ROLLOVER_MAX_DAYS 日以内だけ）。"""
    this_year = _day_of_year(posted.year, julian_day)
    if this_year is not None and this_year >= posted:
        return this_year
    next_year = _day_of_year(posted.year + 1, julian_day)
    if next_year is not None and (next_year - posted).days <= ROLLOVER_MAX_DAYS:
        return next_year
    return None


def _day_of_year(year: int, julian_day: int) -> date | None:
    day = date(year, 1, 1) + timedelta(days=julian_day - 1)
    return day if day.year == year else None


def rule_bp1(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Conclusion]:
    """BP1 搭乗券：氏名（full_name）と、搭乗日からの留守の予定（long_term_home_absence）。"""
    found = boarding_passes(clues, posts)
    if not found:
        return []
    i, bp, _ = found[0]
    pnr = PNR_NOTE if any(leg.has_pnr for f in found for leg in f[1].legs) else ""
    name = f"{bp.family_name} {bp.given_name}".strip()
    note = _join("搭乗券のバーコードの氏名（ローマ字）", pnr)
    conclusions = [Conclusion("BP1", "full_name", name, [i], note)]
    # 留守の予定は、予定として読める搭乗券のうち最初のもの（終わった旅行の搭乗券は飛ばす）
    planned = next(
        ((j, p, plan) for j, p, post in found if (plan := _boarding_plan(j, p, post))), None
    )
    if planned is not None:
        i, bp, plan = planned
        leg = bp.legs[0]
        route = "→".join([airport(leg.origin), *(airport(g.destination) for g in bp.legs)])
        conclusions.append(
            Conclusion(
                "BP1",
                "long_term_home_absence",
                f"{plan.when}{route}の便に乗る予定（搭乗券）",
                [i],
                _join("搭乗券のバーコードの搭乗日・出発地・到着地。年は投稿日から決めた", pnr),
            )
        )
    return conclusions


def rule_bp2(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    conclusions: Sequence[Conclusion],
    text_plan: Plan | None,
) -> list[Conclusion]:
    """BP2 住所と留守：家の場所と、別の投稿の留守の予定（long_term_home_absence）。"""
    homes = [c for a in HOME_ATTRIBUTES for c in conclusions if c.attribute == a and c.clue_indices]
    plans = [*_boarding_plans(clues, posts), *([text_plan] if text_plan else [])]
    # 細かい家の場所から順に、別の投稿の予定と組める最初の組み合わせ
    pair = next(
        (
            (home, plan)
            for home in homes
            for plan in plans
            if not {clues[i].post_id for i in plan.clue_indices}
            & {clues[i].post_id for i in home.clue_indices}
            # R1 と本文の予定の組み合わせは X3 がもう出している
            and (plan.from_boarding_pass or home.attribute == "home_block")
        ),
        None,
    )
    if pair is None:
        return []
    home, plan = pair
    place = home.value.strip()
    if not place.endswith("付近"):
        place += "付近"
    return [
        Conclusion(
            "BP2",
            "long_term_home_absence",
            f"{place}の家が、{plan.when}留守になる可能性（{plan.source}）",
            sorted({*home.clue_indices, *plan.clue_indices}),
            f"家の場所の投稿（{home.rule}）と、別の投稿の留守の予定（{plan.source}）を結合",
        )
    ]


def _boarding_plans(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Plan]:
    plans = (_boarding_plan(i, bp, post) for i, bp, post in boarding_passes(clues, posts))
    return [p for p in plans if p is not None]


def _boarding_plan(i: int, bp: BoardingPass, post: Post) -> Plan | None:
    if any(w in post.text for w in PAST_WORDS):
        return None
    day = flight_date(bp.legs[0].julian_day, _local(post).date())
    if day is None:
        return None
    return Plan(f"{day.month}月{day.day}日に", (i,), "搭乗券", True)


def _join(*parts: str) -> str:
    return "。".join(p for p in parts if p)
