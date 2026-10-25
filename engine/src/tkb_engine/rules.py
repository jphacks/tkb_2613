"""推理ルール R1〜R3。手がかりの組み合わせから結論を出す。

入力：
- clues：投稿ごとに抜き出した手がかり（tkb_common.schemas.Clue）を全投稿ぶん並べた一覧。
  結論の根拠は、この一覧での番号（clue_indices）で返す
- posts：診断した投稿（tkb_common.schemas.Post）。R2・R3 は created_at（投稿の時刻）を使う
- gaz：data-prep の表（Gazetteer）。R1 が駅名・郵便番号・住所を引き当てる

出力：Conclusion の一覧。1つの Conclusion が捜査ボードの1行のもとになる。
attribute はまだ試作のときの名前（station / home_area / active_time / routine / line / age）のまま。
プロフィールの16項目（tkb_common.schemas.ProfileAttribute）への対応づけはこれから行う。
station・line → commute_station_or_line、home_area → residential_area はそのまま当てはまる。
R5・R7 は16項目の名前（full_name・given_name_or_nickname・school）をそのまま使う。

ルールの中身：
- R1 生活圏：station_sign / place_text（駅名）と address_text / postal_code（区と町名）から、
  最寄り駅と町名。駅名は手がかりごとに候補へ票を入れ、票のいちばん多い駅にする。
  同じ写真の駅名標は、枠がいちばん大きい駅名をその駅、ほかを隣の駅とみなす
- R2 行動時間：R1 で駅が決まったとき、場所の手がかりがある平日の投稿が、同じ時間帯に
  R2_MIN_POSTS 件以上
- R3 留守の時間：同じ曜日・同じ時間帯の投稿が R3_MIN_POSTS 件以上、または曜日を含む routine_text
- R4 路線：手がかりの文字に出てくる路線名（「千代田線また遅延」など）。R1 の駅がその路線にあるか、
  別々の投稿に同じ路線名が R4_MIN_POSTS 件以上出てくれば、使っている路線（line）とする
- R5 名前：name_text（宛名・名札・呼びかけ）から敬称を除く。姓と名がそろったものを
  フルネーム（full_name）、名だけのものを呼び名（given_name_or_nickname）にする。
  読めない文字 x を含むものは使わない
- R6 年齢：age_text の「◯歳」と、その投稿の日付（age）
- R7 学校：org_text のうち、学校の名前（大学・高校など）を含むもの（school）
- R5〜R7 は、別の値が同じ数だけ出てきて決められないときは結論にしない

ルールを足すときは rule_rN(clues, posts, ...) -> list[Conclusion] を書き、infer に並べる。
しきい値は下の「しきい値」にまとめる。値は eval/fixtures/demo_observations.json で決めた仮の値で、
eval/spike/run.py の結果を見ながら調整する。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import Gazetteer

# ---- しきい値（仮の値） ----
# R1：最寄り駅を決めるのに要る、支持する手がかりの数（駅名＋区を絞った住所・郵便番号）
R1_MIN_EVIDENCE = 2
# R2：「同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R2_WINDOW_HOURS = 1.0
R2_MIN_POSTS = 2
# R3：「同じ曜日の同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R3_WINDOW_HOURS = 1.0
R3_MIN_POSTS = 3
# R3：結論の括弧の中に並べる、生活の決まりの言葉の数（根拠の手がかりはすべて残す）
R3_MAX_WORDS = 2
# R4：R1 の駅がなくても路線を結論にするのに要る、その路線名が出てくる投稿の数
R4_MIN_POSTS = 2
# ----------------------------

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"

R1_NAME_TYPES = {ClueType.STATION_SIGN, ClueType.PLACE_TEXT}
R1_AREA_TYPES = {ClueType.ADDRESS_TEXT, ClueType.POSTAL_CODE}
# 場所の手がかり（R2 で「場所の投稿」とみなす）。shop は店の場所のデータがないので R1 には使わない
LOCATION_TYPES = R1_NAME_TYPES | R1_AREA_TYPES | {ClueType.SHOP}
# 路線名を探す手がかり。「電車混んでる」と同じく、遅延の愚痴は routine_text になることもある
R4_LINE_TYPES = R1_NAME_TYPES | {ClueType.ROUTINE_TEXT}
# R5：名前の前後につく敬称（宛名の「様」、呼びかけの「さん」など）
HONORIFICS = ("様", "さま", "さん", "くん", "君", "ちゃん", "殿", "氏")
# R5：区切りなしでフルネームとみなす、漢字の文字数（「内藤大貴」は4文字、名だけの「大貴」は2文字）
FULL_NAME_MIN_KANJI = 3
# R7：学校とみなす言葉
SCHOOL_WORDS = ("大学", "高校", "高等学校", "高等専門学校", "高専", "専門学校", "中学校")


@dataclass(frozen=True)
class Conclusion:
    """ルールが出した結論。

    - rule：出したルール（"R1" など）
    - attribute：項目の名前（モジュールの説明を参照）
    - value：画面に出す値
    - clue_indices：根拠の手がかりの、clues での番号
    - note：どう結論したかのメモ（推理の実況に使える）
    """

    rule: str
    attribute: str
    value: str
    clue_indices: list[int]
    note: str = ""


def rule_r1(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    """R1 生活圏：町名（home_area）と最寄り駅（station）。"""
    name_hits = {
        i: names
        for i, c in enumerate(clues)
        if c.type in R1_NAME_TYPES and (names := gaz.station_names(c.value))
    }
    area_hits = {
        i: hit for i, c in enumerate(clues) if c.type in R1_AREA_TYPES and (hit := gaz.area(c))[0]
    }

    conclusions: list[Conclusion] = []

    # 町名：住所と郵便番号の候補の重なり
    munis: set[str] = set()
    if area_hits:
        munis = set.intersection(*(m for m, _ in area_hits.values()))
        towns = set.intersection(*(t for _, t in area_hits.values()))
        if len(towns) == 1:
            conclusions.append(
                Conclusion(
                    "R1",
                    "home_area",
                    next(iter(towns)),
                    sorted(area_hits),
                    "住所と郵便番号の重なり",
                )
            )

    # 最寄り駅：駅名の手がかりごとに候補へ票を入れ、区のメッシュで絞って、票のいちばん多い駅
    station = _vote_station(clues, name_hits, munis, gaz)
    if station is not None:
        name, evidence, used_area = station
        if used_area:
            evidence |= set(area_hits)
        if len(evidence) >= R1_MIN_EVIDENCE:
            note = "駅名の手がかりの票がいちばん多い駅"
            if used_area:
                note += "。住所・郵便番号の区で絞った"
            conclusions.append(Conclusion("R1", "station", f"{name}駅", sorted(evidence), note))
    return conclusions


def rule_r2(clues: Sequence[Clue], posts: Sequence[Post], r1: list[Conclusion]) -> list[Conclusion]:
    """R2 行動時間：平日のどの時間帯に R1 の駅のまわりにいるか（active_time）。"""
    station = next((c for c in r1 if c.attribute == "station"), None)
    if station is None:
        return []
    location_posts = {c.post_id for c in clues if c.type in LOCATION_TYPES}
    weekday = [p for p in posts if p.post_id in location_posts and _local(p).weekday() < 5]
    group = _largest_cluster(weekday, R2_WINDOW_HOURS)
    if len(group) < R2_MIN_POSTS:
        return []
    ids = {p.post_id for p in group}
    indices = [i for i, c in enumerate(clues) if c.post_id in ids and c.type in LOCATION_TYPES]
    return [
        Conclusion(
            "R2",
            "active_time",
            f"平日 {_hour_label(group)}に{station.value}のまわりにいる",
            indices,
            f"場所の投稿 {len(group)} 件",
        )
    ]


def rule_r3(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Conclusion]:
    """R3 留守の時間：毎週決まった曜日・時間帯に出かけている（routine）。"""
    conclusions: list[Conclusion] = []
    routine = {i: c for i, c in enumerate(clues) if c.type is ClueType.ROUTINE_TEXT}

    for day in range(7):
        same_day = [p for p in posts if _local(p).weekday() == day]
        group = _largest_cluster(same_day, R3_WINDOW_HOURS)
        if len(group) < R3_MIN_POSTS:
            continue
        ids = {p.post_id for p in group}
        indices = [i for i, c in routine.items() if c.post_id in ids]
        words = _short_words([routine[i].value for i in indices])
        detail = f"（{'・'.join(words)}）" if words else ""
        conclusions.append(
            Conclusion(
                "R3",
                "routine",
                f"毎週{WEEKDAYS[day]}曜 {_hour_label(group)}に出かけている{detail}",
                indices,
                f"同じ曜日・時間帯の投稿 {len(group)} 件（根拠の番号は、その投稿の routine_text）",
            )
        )

    # 曜日を含む routine_text だけでも結論にする（投稿の時刻がそろわなくても）
    for i, c in routine.items():
        m = re.search(f"([{WEEKDAYS}])曜", c.value)
        if m and not any(f"{m[1]}曜" in con.value and i in con.clue_indices for con in conclusions):
            conclusions.append(
                Conclusion("R3", "routine", f"毎週{m[1]}曜（{c.value}）", [i], "本文の曜日")
            )
    return conclusions


def rule_r4(clues: Sequence[Clue], r1: list[Conclusion], gaz: Gazetteer) -> list[Conclusion]:
    """R4 路線：使っている路線（line）。"""
    mentions: dict[str, list[int]] = {}
    for i, c in enumerate(clues):
        if c.type in R4_LINE_TYPES:
            for line in gaz.line_names(c.value):
                mentions.setdefault(line, []).append(i)
    if not mentions:
        return []

    station = next((c for c in r1 if c.attribute == "station"), None)
    station_lines = gaz.lines_of(station.value.removesuffix("駅")) if station else set()

    def posts_of(line: str) -> int:
        return len({clues[i].post_id for i in mentions[line]})

    on_station = [line for line in mentions if line in station_lines]
    if on_station:
        line = max(on_station, key=lambda n: (posts_of(n), n))
        note = f"本文の路線名が、最寄り駅（{station.value if station else ''}）の路線と一致"
    else:
        line = max(mentions, key=lambda n: (posts_of(n), n))
        if posts_of(line) < R4_MIN_POSTS:
            return []
        note = f"同じ路線名が {posts_of(line)} 件の投稿に出てくる"
    return [Conclusion("R4", "line", line, mentions[line], note)]


def rule_r5(clues: Sequence[Clue]) -> list[Conclusion]:
    """R5 名前：フルネーム（full_name）と呼び名（given_name_or_nickname）。"""
    full: dict[str, list[int]] = {}
    given: dict[str, list[int]] = {}
    for i, c in enumerate(clues):
        if c.type is not ClueType.NAME_TEXT:
            continue
        name = _strip_honorifics(c.value)
        if not name or "x" in name.lower():
            continue
        if _is_full_name(name):
            full.setdefault(name.replace(" ", ""), []).append(i)
        else:
            given.setdefault(name, []).append(i)

    conclusions: list[Conclusion] = []
    if (best := _most_frequent(full)) is not None:
        conclusions.append(
            Conclusion("R5", "full_name", best, full[best], "宛名・名札などの姓と名")
        )
    if (best := _most_frequent(given)) is not None:
        conclusions.append(
            Conclusion("R5", "given_name_or_nickname", best, given[best], "名前だけの手がかり")
        )
    return conclusions


def rule_r6(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Conclusion]:
    """R6 年齢：いちばん新しい投稿の「◯歳」と、その投稿の年月（age）。"""
    created = {p.post_id: _local(p) for p in posts}
    ages = [
        (created[c.post_id], int(m[1]), i)
        for i, c in enumerate(clues)
        if c.type is ClueType.AGE_TEXT
        and c.post_id in created
        and (m := re.search(r"(\d{1,3})\s*歳", c.value))
    ]
    if not ages:
        return []
    when, age, index = max(ages)
    return [
        Conclusion(
            "R6",
            "age",
            f"{age}歳（{when.year}年{when.month}月の投稿）",
            [index],
            "本文の年齢と投稿の日付",
        )
    ]


def rule_r7(clues: Sequence[Clue]) -> list[Conclusion]:
    """R7 学校：学校の名前を含む org_text（school）。"""
    schools: dict[str, list[int]] = {}
    for i, c in enumerate(clues):
        value = c.value.strip()
        if (
            c.type is ClueType.ORG_TEXT
            and "x" not in value.lower()
            and any(w in value for w in SCHOOL_WORDS)
        ):
            schools.setdefault(value, []).append(i)
    best = _most_frequent(schools)
    if best is None:
        return []
    return [Conclusion("R7", "school", best, schools[best], "学校の名前の手がかり")]


def infer(clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer) -> list[Conclusion]:
    """すべてのルールを順に当てはめる。R2・R4 は R1 の結論を使う。"""
    r1 = rule_r1(clues, gaz)
    return [
        *r1,
        *rule_r2(clues, posts, r1),
        *rule_r3(clues, posts),
        *rule_r4(clues, r1, gaz),
        *rule_r5(clues),
        *rule_r6(clues, posts),
        *rule_r7(clues),
    ]


def _short_words(values: Sequence[str]) -> list[str]:
    """括弧の中に並べる言葉。多く出てきた順、同じなら短い順に R3_MAX_WORDS 個まで。

    片方がもう片方を含む言葉（「電車混んでる」と「月曜の朝から電車混んでる」）は、先に選んだ方だけにする。
    """
    counts: dict[str, int] = {}
    for value in values:
        word = value.strip()
        if word:
            counts[word] = counts.get(word, 0) + 1
    picked: list[str] = []
    for word in sorted(counts, key=lambda w: (-counts[w], len(w), w)):
        if not any(word in p or p in word for p in picked):
            picked.append(word)
        if len(picked) == R3_MAX_WORDS:
            break
    return picked


def _strip_honorifics(value: str) -> str:
    """前後の空白と敬称を除き、全角の空白を半角にする。"""
    name = value.replace("\u3000", " ").strip()
    for honorific in HONORIFICS:
        name = name.removesuffix(honorific).strip()
    return " ".join(name.split())


def _is_full_name(name: str) -> bool:
    """「内藤 大貴」のように区切りがあるか、区切りなしの漢字が FULL_NAME_MIN_KANJI 文字以上。"""
    if " " in name:
        return len(name.split()) == 2
    return len(name) >= FULL_NAME_MIN_KANJI and all("\u4e00" <= ch <= "\u9fff" for ch in name)


def _most_frequent(candidates: dict[str, list[int]]) -> str | None:
    """いちばん多く出てきた値。同じ数の値がほかにもあれば決めない（None）。"""
    if not candidates:
        return None
    best = max(len(v) for v in candidates.values())
    winners = [k for k, v in candidates.items() if len(v) == best]
    return winners[0] if len(winners) == 1 else None


def _region_area(clue: Clue) -> int:
    if clue.region is None:
        return 0
    x1, y1, x2, y2 = clue.region
    return (x2 - x1) * (y2 - y1)


def _sign_groups(clues: Sequence[Clue], name_hits: dict[int, set[str]]) -> dict[int, list[int]]:
    """同じ写真の駅名標の手がかりをまとめ、{その駅の番号: 隣の駅の番号の一覧} を返す。

    駅名標には、その駅の名前と隣の駅の名前が並ぶ。枠がいちばん大きいものをその駅とみなす。
    写真の駅名標でない駅名の手がかり（本文の place_text など）は、隣の駅なしで1つずつ。
    """
    groups: dict[tuple[str, int], list[int]] = {}
    singles: dict[int, list[int]] = {}
    for i in name_hits:
        clue = clues[i]
        if clue.type is ClueType.STATION_SIGN and clue.image_index is not None:
            groups.setdefault((clue.post_id, clue.image_index), []).append(i)
        else:
            singles[i] = []
    for members in groups.values():
        # 枠の大きさが同じなら、先に出たもの（モデルはふつう大きく書かれた駅名から挙げる）
        main = max(members, key=lambda i: (_region_area(clues[i]), -i))
        singles[main] = [i for i in members if i != main]
    return singles


def _vote_station(
    clues: Sequence[Clue],
    name_hits: dict[int, set[str]],
    munis: set[str],
    gaz: Gazetteer,
) -> tuple[str, set[int], bool] | None:
    """(駅名, 根拠の手がかりの番号, 区で絞ったか)。決められなければ None。"""
    votes: dict[str, set[int]] = {}
    for main, neighbors in _sign_groups(clues, name_hits).items():
        for name in name_hits[main]:
            votes.setdefault(name, set()).add(main)
            # 隣の駅名は、その駅の根拠に入れる（自分自身の票にはしない）
            votes[name].update(neighbors)
    if not votes:
        return None

    used_area = False
    if munis:
        in_area = {name: ids for name, ids in votes.items() if name in gaz.stations_in(munis)}
        if in_area:
            votes, used_area = in_area, True

    def score(name: str) -> int:
        # 票は「その駅」として挙がった手がかりの数（隣の駅としての根拠は数えない）
        return sum(1 for i in votes[name] if name in name_hits[i])

    best = max(score(name) for name in votes)
    winners = [name for name in votes if score(name) == best]
    if len(winners) != 1:
        return None
    return winners[0], set(votes[winners[0]]), used_area


def _local(post: Post) -> datetime:
    return post.created_at.astimezone(JST)


def _hour(post: Post) -> float:
    t = _local(post)
    return t.hour + t.minute / 60


def _largest_cluster(posts: list[Post], window: float) -> list[Post]:
    """時刻（時:分）が ±window 時間に収まる投稿の、いちばん大きいまとまり。"""
    best: list[Post] = []
    for center in posts:
        group = [p for p in posts if abs(_hour(p) - _hour(center)) <= window]
        if len(group) > len(best):
            best = group
    return best


def _hour_label(posts: list[Post]) -> str:
    return f"{round(sum(_hour(p) for p in posts) / len(posts))}時ごろ"
