"""消したらどうなるか（simulate）と、危ない投稿の選び方（plan）。

どちらもモデルを呼ばない。抜き出し済みの手がかりから、消す投稿の分を除いて infer をかけ直すだけ。
元の clues と posts は書き換えない。

- simulate：選んだ投稿を消したときの、前後の結論と崩れる項目
- plan：重要な項目（IMPORTANT_ATTRIBUTES）が不明になるまで、効き目の大きい投稿から順に
  最大 PLAN_MAX_POSTS 件を選ぶ（貪欲法）

「崩れる」は、消す前にその項目の結論が1つ以上あり、消したあと1つもなくなること。
値が別の値に変わった場合（別の駅になるなど）は、まだ推定できているので崩れたとしない。
"""

from collections.abc import Sequence
from dataclasses import dataclass

from tkb_common.schemas import Clue, Post
from tkb_engine.gazetteer import Gazetteer
from tkb_engine.rules import Conclusion, infer

# 最寄り駅・住所の区画・行動時間・留守の時間。これが崩れれば、待ち伏せや空き巣の手がかりがなくなる
IMPORTANT_ATTRIBUTES = ("station", "home_block", "active_time", "routine")
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
    """重要な項目を崩す投稿を選び、その投稿を消したときの結果を返す。

    候補は、いま残っている重要な結論の根拠になっている投稿。1件ずつ足してみて、
    (残る重要な項目の数, 重要な結論の根拠の手がかりの数, 残る項目の数) がいちばん小さくなる
    投稿を選ぶ。
    同じなら、根拠になっている回数の多い投稿、さらに同じなら posts で先の投稿。
    2つ目の数を見るのは、根拠が多い駅のように1件では崩れない項目も、少しずつ崩せるようにするため。
    どの候補でも小さくならないときは、そこでやめる。
    """
    chosen: list[str] = []
    current = _score(infer(clues, posts, gaz))
    while current[0] > 0 and len(chosen) < PLAN_MAX_POSTS:
        best: tuple[tuple[int, int, int], int, str] | None = None
        for rank, post_id in enumerate(_candidates(clues, posts, gaz, chosen)):
            sim = simulate(clues, posts, gaz, [*chosen, post_id])
            score = _score(sim.after)
            if score < current and (best is None or (score, rank) < (best[0], best[1])):
                best = (score, rank, post_id)
        if best is None:
            break
        current = best[0]
        chosen.append(best[2])
    return simulate(clues, posts, gaz, chosen)


def _important(conclusions: Sequence[Conclusion]) -> list[Conclusion]:
    return [c for c in conclusions if c.attribute in IMPORTANT_ATTRIBUTES]


def _score(conclusions: Sequence[Conclusion]) -> tuple[int, int, int]:
    important = _important(conclusions)
    evidence = {i for c in important for i in c.clue_indices}
    return (
        len({c.attribute for c in important}),
        len(evidence),
        len({c.attribute for c in conclusions}),
    )


def _candidates(
    clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer, chosen: Sequence[str]
) -> list[str]:
    """chosen を消したあとに残る重要な結論の、根拠の投稿。根拠になった回数の多い順。"""
    sim = simulate(clues, posts, gaz, chosen)
    counts: dict[str, int] = {}
    for conclusion in _important(sim.after):
        for i in conclusion.clue_indices:
            post_id = sim.after_clues[i].post_id
            counts[post_id] = counts.get(post_id, 0) + 1
    order = {p.post_id: n for n, p in enumerate(posts)}
    return sorted(counts, key=lambda post_id: (-counts[post_id], order.get(post_id, len(order))))


def _broken(before: Sequence[Conclusion], after: Sequence[Conclusion]) -> list[str]:
    remaining = {c.attribute for c in after}
    return list(dict.fromkeys(c.attribute for c in before if c.attribute not in remaining))
