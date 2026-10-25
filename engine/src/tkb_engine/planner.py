"""消したらどうなるか（simulate）と、危ない投稿の選び方（plan）。

どちらもモデルを呼ばない。抜き出し済みの手がかりから、消す投稿の分を除いて infer をかけ直すだけ。
元の clues と posts は書き換えない。

- simulate：選んだ投稿を消したときの、前後の結論と崩れる項目
- plan：身元や居場所の推定、写真に写った危険な手がかりを重く見て、最大
  PLAN_MAX_POSTS 件を選ぶ（貪欲法）。最後に効果のない投稿を外す

「崩れる」は、消す前にその項目の結論が1つ以上あり、消したあと1つもなくなること。
値が別の値に変わった場合（別の駅になるなど）は、まだ推定できているので崩れたとしない。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from tkb_common.name_text import is_person_name_text
from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import Conclusion, infer

# 名前・生年月日・住まいを先に守る。顔は本人かどうか推定せず、写った事実だけを扱う。
ATTRIBUTE_WEIGHTS = {
    "full_name": 120,
    "birthday": 110,
    "home_block": 105,
    "home_area": 100,
    "long_term_home_absence": 98,
    "home_district": 95,
    "home_city": 90,
    "workplace": 88,
    "school": 85,
    "home_school_commute": 80,
    "given_name_or_nickname": 70,
    "station": 65,
    "age": 55,
    "frequent_shop": 50,
    "line": 40,
    "active_time": 30,
    "routine": 25,
}
IMPORTANT_ATTRIBUTES = tuple(ATTRIBUTE_WEIGHTS)
DIRECT_CLUE_WEIGHTS = {
    ClueType.FACE: 100,
    ClueType.NAME_TEXT: 70,
    ClueType.ADDRESS_TEXT: 70,
    ClueType.PHONE: 65,
    ClueType.POSTAL_CODE: 45,
}
PLAN_MAX_POSTS = 3


@dataclass(frozen=True)
class Simulation:
    """投稿を消したときの結果。

    - delete：消す投稿の ID（受け取った順）
    - broken：崩れる項目（attribute）。消す前の結論の並び順
    - before / after：消す前・消したあとの結論。clue_indices はそれぞれ
      before_clues / after_clues での番号
    """

    delete: list[str]
    broken: list[str]
    before: list[Conclusion]
    after: list[Conclusion]
    before_clues: list[Clue]
    after_clues: list[Clue]


def simulate(
    clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer, delete: Sequence[str]
) -> Simulation:
    """delete の投稿を消したとして、推理をかけ直す。"""
    gone = set(delete)
    after_clues = [c for c in clues if c.post_id not in gone]
    after_posts = [p for p in posts if p.post_id not in gone]
    before = infer(clues, posts, gaz)
    after = infer(after_clues, after_posts, gaz)
    return Simulation(
        delete=list(dict.fromkeys(delete)),
        broken=_broken(before, after),
        before=before,
        after=after,
        before_clues=list(clues),
        after_clues=after_clues,
    )


def plan(clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer) -> Simulation:
    """個人を特定しやすい推定と、写真に直接写った手がかりを減らす投稿を選ぶ。"""
    chosen: list[str] = []
    current_sim = simulate(clues, posts, gaz, chosen)
    current = _score(current_sim.after, current_sim.after_clues)
    while current[0] > 0 and len(chosen) < PLAN_MAX_POSTS:
        best: tuple[tuple[int, int], int, str] | None = None
        for rank, post_id in enumerate(_candidates(clues, posts, gaz, chosen)):
            sim = simulate(clues, posts, gaz, [*chosen, post_id])
            score = _score(sim.after, sim.after_clues)
            if score < current and (best is None or (score, rank) < (best[0], best[1])):
                best = (score, rank, post_id)
        if best is None:
            break
        current = best[0]
        chosen.append(best[2])
    # 根拠の数だけ減って、危険な推定や写真は残る候補は勧めない。
    # 最大3件なので全ての部分集合を比べ、同じ効果なら少ない件数を選べる。
    baseline = _score(infer(clues, posts, gaz), clues)[0]
    best_ids: tuple[str, ...] = ()
    best_risk = baseline
    for count in range(1, len(chosen) + 1):
        for subset in combinations(chosen, count):
            sim = simulate(clues, posts, gaz, subset)
            risk = _score(sim.after, sim.after_clues)[0]
            if risk < best_risk:
                best_ids, best_risk = subset, risk
    return simulate(clues, posts, gaz, best_ids)


def _important(conclusions: Sequence[Conclusion]) -> list[Conclusion]:
    return [c for c in conclusions if c.attribute in IMPORTANT_ATTRIBUTES]


def _direct_weight(clue: Clue) -> int:
    if clue.type is ClueType.FACE and clue.confidence < 0.8:
        return 0
    if clue.type is ClueType.NAME_TEXT and not is_person_name_text(clue.value):
        return 0
    return DIRECT_CLUE_WEIGHTS.get(clue.type, 0)


def _score(conclusions: Sequence[Conclusion], clues: Sequence[Clue]) -> tuple[int, int]:
    important = _important(conclusions)
    inferred_risk = sum(ATTRIBUTE_WEIGHTS[a] for a in {c.attribute for c in important})
    direct_risk = sum(_direct_weight(c) for c in clues)
    evidence = {i for c in important for i in c.clue_indices}
    return inferred_risk + direct_risk, len(evidence)


def _candidates(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    gaz: Gazetteer,
    chosen: Sequence[str],
) -> list[str]:
    """残る重要な結論の根拠と、危険な写真・文字がある投稿。"""
    sim = simulate(clues, posts, gaz, chosen)
    counts: dict[str, int] = {}
    for conclusion in sim.after:
        if conclusion.attribute not in IMPORTANT_ATTRIBUTES:
            continue
        for i in conclusion.clue_indices:
            post_id = sim.after_clues[i].post_id
            counts[post_id] = counts.get(post_id, 0) + 1
    for clue in sim.after_clues:
        if _direct_weight(clue):
            counts[clue.post_id] = counts.get(clue.post_id, 0) + 1
    order = {p.post_id: n for n, p in enumerate(posts)}
    return sorted(counts, key=lambda post_id: (-counts[post_id], order.get(post_id, len(order))))


def _broken(before: Sequence[Conclusion], after: Sequence[Conclusion]) -> list[str]:
    remaining = {c.attribute for c in after}
    return list(dict.fromkeys(c.attribute for c in before if c.attribute not in remaining))
