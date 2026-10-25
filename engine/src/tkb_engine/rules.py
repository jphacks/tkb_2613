"""推理ルール R1〜R10。手がかりの組み合わせから結論を出す。

入力：
- clues：投稿ごとに抜き出した手がかり（tkb_common.schemas.Clue）を全投稿ぶん並べた一覧。
  結論の根拠は、この一覧での番号（clue_indices）で返す
- posts：診断した投稿（tkb_common.schemas.Post）。R2・R3 は created_at（投稿の時刻）を使う
- gaz：data-prep の表と知識表（Gazetteer）。駅名・郵便番号・住所・指定ゴミ袋・収集地区・
  大学を引き当てる

出力：Conclusion の一覧。1つの Conclusion が捜査ボードの1行のもとになる。
attribute はまだ試作の名前。プロフィールの16項目（tkb_common.schemas.ProfileAttribute）への
対応づけはこれから行う。station → commute_station_or_line、home_city・home_district・home_area・
home_block → residential_area、school → school、name → given_name_or_nickname が当てはまる。
age・occupation・active_time・routine は16項目にない。

ルールの中身：
- R1 生活圏：station_sign / place_text（駅名）と address_text / postal_code（区と町名）から、
  最寄り駅と町名。駅名は手がかりごとに候補へ票を入れ、票のいちばん多い駅にする。
  同じ写真の駅名標は、枠がいちばん大きい駅名をその駅、ほかを隣の駅とみなす。
  店名・看板・映り込み・掲示に「〇〇駅」（「八王子駅前店」など）があれば、その駅にも票を入れる。
  住所・郵便番号がなければ、R4・R5 の市区町村で駅を絞り、その根拠も駅の根拠に入れる
- R2 行動時間：R1 で駅が決まったとき、場所の手がかりがある平日の投稿が、同じ時間帯に
  R2_MIN_POSTS 件以上
- R3 留守の時間：同じ曜日・同じ時間帯の投稿が R3_MIN_POSTS 件以上、または曜日を含む routine_text
- R4 市区町村：指定ゴミ袋（local_item）の色・容量・枚数・値段を知識表と照らす。
  ゴミ集積所などの掲示（notice）・品物に書かれた市区町村名も使う
- R5 収集地区：R4 の市区町村で、集積所の掲示（notice）の燃やすごみの曜日が合う収集地区
- R6 区画：郵便物のカスタマバーコードの中身（code）や住所表示（address_text）の郵便番号・町名と番地
- R7 通学先：「大学」と「〇限」の本文を、R4 の市区町村にある大学の時間割と照らす
- R8 名前：name_text（ケーキのプレート、宛名、返信での呼びかけなど）を、敬称や読めない字を
  落としてまとめる
- R9 年齢：age_text の「〇歳」。誕生日にお酒（「堂々と頼めた🍺」など）なら 20歳。誕生日は投稿日
- R10 仕事：夜勤などの生活の決まりと、作業靴・白衣などの身なり

ルールを足すときは rule_rN(clues, posts, ...) -> list[Conclusion] を書き、infer に並べる。
しきい値は下の「しきい値」にまとめる。値は eval/fixtures/demo_observations.json で決めた仮の値で、
eval/spike/run.py の結果を見ながら調整する。
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import Gazetteer, TrashBag

# ---- しきい値（仮の値） ----
# R1：最寄り駅を決めるのに要る、支持する手がかりの数（駅名＋区を絞った住所・郵便番号）
R1_MIN_EVIDENCE = 2
# R2：「同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R2_WINDOW_HOURS = 1.0
R2_MIN_POSTS = 2
# R3：「同じ曜日の同じ時間帯」とみなす幅（±時間）と、要る投稿の数
R3_WINDOW_HOURS = 1.0
R3_MIN_POSTS = 3
# R8：名前の手がかりの確からしさを 1 − ∏(1 − c) で合わせたとき、名前とみなす下限
R8_MIN_CONFIDENCE = 0.7
# R7：「〇限」の投稿が、その時限の始まりより何時間前までなら合うとみなすか（休み時間の投稿）
R7_EARLY_HOURS = 0.5
# ----------------------------

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = "月火水木金土日"

R1_NAME_TYPES = {ClueType.STATION_SIGN, ClueType.PLACE_TEXT}
R1_AREA_TYPES = {ClueType.ADDRESS_TEXT, ClueType.POSTAL_CODE}
# 「〇〇駅」が書かれていれば R1 で駅の票にする type（店名・看板・映り込みなど）
R1_MENTION_TYPES = {
    ClueType.SHOP,
    ClueType.REFLECTION,
    ClueType.LANDMARK,
    ClueType.NOTICE,
    ClueType.ORG_TEXT,
}
# 場所の手がかり（R2 で「場所の投稿」とみなす）。rail_view は駅にいること
LOCATION_TYPES = R1_NAME_TYPES | R1_AREA_TYPES | {ClueType.SHOP, ClueType.RAIL_VIEW}


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


def rule_r1(
    clues: Sequence[Clue], gaz: Gazetteer, area: Sequence[Conclusion] = ()
) -> list[Conclusion]:
    """R1 生活圏：町名（home_area）と最寄り駅（station）。

    area は R4・R5 の結論（先頭が R4 の市区町村、続いて収集地区）。住所・郵便番号の手がかりが
    ないとき、駅を絞るのに使い、その根拠も駅の根拠に入れる。
    """
    name_hits = {
        i: names
        for i, c in enumerate(clues)
        if (c.type in R1_NAME_TYPES and (names := gaz.station_names(c.value)))
        or (c.type in R1_MENTION_TYPES and (names := _mentioned_stations(c.value, gaz)))
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

    # 住所・郵便番号がなければ、R4・R5 の市区町村で絞る
    area_evidence = set(area_hits)
    area_note = "住所・郵便番号の区で絞った"
    if not munis and area:
        # area の先頭は R4 の市区町村
        munis = gaz.city_munis(area[0].value)
        area_evidence = {i for a in area for i in a.clue_indices}
        area_note = f"{area[0].value}で絞った"

    # 最寄り駅：駅名の手がかりごとに候補へ票を入れ、区のメッシュで絞って、票のいちばん多い駅
    station = _vote_station(clues, name_hits, munis, gaz)
    if station is not None:
        name, evidence, used_area = station
        if used_area:
            evidence |= area_evidence
        if len(evidence) >= R1_MIN_EVIDENCE:
            note = "駅名の手がかりの票がいちばん多い駅"
            if used_area:
                note += "。" + area_note
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
        words = sorted({c.value for i, c in routine.items() if i in indices})
        conclusions.append(
            Conclusion(
                "R3",
                "routine",
                f"毎週{WEEKDAYS[day]}曜 {_hour_label(group)}に出かけている（{'・'.join(words)}）",
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


def rule_r4(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    """R4 市区町村（home_city）：指定ゴミ袋と、掲示・品物に書かれた市区町村名。"""
    votes: dict[str, set[int]] = {}
    for i, c in enumerate(clues):
        if c.type is ClueType.LOCAL_ITEM:
            cities = {b.city for b in _matching_bags(c.value, gaz)}
            if len(cities) == 1:
                votes.setdefault(next(iter(cities)), set()).add(i)
        if c.type in {ClueType.LOCAL_ITEM, ClueType.NOTICE}:
            for city in gaz.cities_in(c.value):
                votes.setdefault(city, set()).add(i)
    if len(votes) != 1:
        # 手がかりがないか、市区町村が食い違う
        return []
    city, evidence = next(iter(votes.items()))
    return [Conclusion("R4", "home_city", city, sorted(evidence), "指定ゴミ袋や掲示の市区町村")]


def rule_r5(clues: Sequence[Clue], gaz: Gazetteer, r4: list[Conclusion]) -> list[Conclusion]:
    """R5 収集地区（home_district）：集積所の掲示の燃やすごみの曜日。"""
    if not r4:
        return []
    city = r4[0].value
    for i, c in enumerate(clues):
        if c.type is not ClueType.NOTICE or not (days := _burnable_days(c.value)):
            continue
        areas = [
            a
            for a in gaz.knowledge.collection_areas
            if a.city == city and set(a.burnable_days) == days
        ]
        if len(areas) == 1:
            label = "・".join(d for d in WEEKDAYS if d in days)
            return [
                Conclusion(
                    "R5",
                    "home_district",
                    f"{city} {areas[0].area}",
                    sorted({i, *r4[0].clue_indices}),
                    f"集積所の燃やすごみの曜日（{label}）が合う地区",
                )
            ]
    return []


def rule_r6(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    """R6 区画（home_block）：郵便番号・町名と番地。郵便物のバーコードの中身や住所表示から。"""
    for i, c in enumerate(clues):
        if c.type not in {ClueType.CODE, ClueType.ADDRESS_TEXT}:
            continue
        # 住所が入っているのはカスタマバーコード（郵便物）だけ。宅配伝票などの番号は郵便番号と
        # 見分けがつかないので使わない
        if (
            c.type is ClueType.CODE
            and ("カスタマバーコード" in c.value or "〒" in c.value)
            and (m := POSTAL_IN_TEXT.search(c.value))
        ):
            rows = gaz.postal_rows(m[1] + m[2])
            if len({(r["city"], r["town"]) for r in rows}) != 1:
                continue
            numbers = re.findall(r"\d+", c.value[m.end() :])[:2]
            if not numbers:
                continue
            place = rows[0]["city"] + _town_name(rows[0]["town"])
            value = f"{place} {'-'.join(numbers)} 付近"
            return [Conclusion("R6", "home_block", value, [i], "郵便物のカスタマバーコードの中身")]
        if c.type is ClueType.ADDRESS_TEXT and (block := BLOCK_IN_ADDRESS.search(c.value)):
            _, towns = gaz.area(c)
            if len(towns) != 1:
                continue
            evidence = [i] + [
                j
                for j, d in enumerate(clues)
                if d.type is ClueType.POSTAL_CODE and d.post_id == c.post_id
            ]
            value = f"{next(iter(towns))}{block[0]}付近"
            return [Conclusion("R6", "home_block", value, sorted(evidence), "住所表示の丁目・番地")]
    return []


def rule_r7(
    clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer, r4: list[Conclusion]
) -> list[Conclusion]:
    """R7 通学先（school）：「大学」と「〇限」の投稿を、市区町村の大学の時間割と照らす。"""
    if not r4:
        return []
    city = r4[0].value
    times = {p.post_id: _hour(p) for p in posts}
    texts = {i: c for i, c in enumerate(clues) if c.type is ClueType.ROUTINE_TEXT}
    college = [i for i, c in texts.items() if "大学" in c.value]
    periods = [
        (i, int(m[1]), times[c.post_id])
        for i, c in texts.items()
        if (m := re.search(r"([1-7１-７])\s*限", c.value)) and c.post_id in times
    ]
    if not college or not periods:
        return []
    candidates = [
        u
        for u in gaz.knowledge.universities
        if u.city == city
        and all(
            n in u.periods and u.periods[n][0] - R7_EARLY_HOURS <= t <= u.periods[n][1]
            for _, n, t in periods
        )
    ]
    if len(candidates) != 1:
        return []
    u = candidates[0]
    walk = any("歩いて" in texts[i].value or "徒歩" in texts[i].value for i in college)
    value = f"{u.name} {u.campus}" + ("（歩いて通える所に住んでいる）" if walk else "")
    evidence = sorted({*college, *(i for i, _, _ in periods), *r4[0].clue_indices})
    return [Conclusion("R7", "school", value, evidence, f"{city}の大学で時間割が合うのはここだけ")]


def rule_r8(clues: Sequence[Clue]) -> list[Conclusion]:
    """R8 名前（name）：name_text をまとめ、確からしさを合わせて下限を超えた名前。"""
    groups: dict[str, list[int]] = {}
    shown: dict[str, str] = {}
    for i, c in enumerate(clues):
        if c.type is ClueType.NAME_TEXT and (name := _clean_name(c.value)):
            key = _hiragana(name)
            groups.setdefault(key, []).append(i)
            shown.setdefault(key, name)
    best: tuple[float, str] | None = None
    for key, indices in groups.items():
        miss = 1.0
        for i in indices:
            miss *= 1 - clues[i].confidence
        if best is None or 1 - miss > best[0]:
            best = (1 - miss, key)
    if best is None or best[0] < R8_MIN_CONFIDENCE:
        return []
    indices = groups[best[1]]
    note = f"名前の手がかり {len(indices)} 件（合わせた確からしさ {best[0]:.2f}）"
    return [Conclusion("R8", "name", shown[best[1]], indices, note)]


def rule_r9(clues: Sequence[Clue], posts: Sequence[Post]) -> list[Conclusion]:
    """R9 年齢（age）：「〇歳」、またはお酒が解禁された誕生日。誕生日は投稿日。"""
    by_id = {p.post_id: p for p in posts}
    for i, c in enumerate(clues):
        if c.type is not ClueType.AGE_TEXT:
            continue
        post = by_id.get(c.post_id)
        text = c.value + (post.text if post else "")
        birthday = BIRTHDAY.search(text)
        if m := re.search(r"(\d{1,3})\s*歳", text):
            age, note = f"{m[1]}歳", "本文の年齢"
        elif birthday and ALCOHOL.search(text):
            age, note = "20歳", "誕生日にお酒を頼めるようになった"
        else:
            continue
        if birthday and post is not None:
            t = _local(post)
            age += f"（誕生日は{t.month}月{t.day}日ごろ）"
            note += "。誕生日は投稿日"
        return [Conclusion("R9", "age", age, [i], note)]
    return []


def rule_r10(clues: Sequence[Clue]) -> list[Conclusion]:
    """R10 仕事（occupation）：シフトの言葉と身なり。"""
    shift = [
        i for i, c in enumerate(clues) if c.type is ClueType.ROUTINE_TEXT and SHIFT.search(c.value)
    ]
    kinds = {
        i: kind
        for i, c in enumerate(clues)
        if c.type is ClueType.UNIFORM
        for pattern, kind in OUTFITS
        if re.search(pattern, c.value)
    }
    if not shift and not kinds:
        return []
    kind = Counter(kinds.values()).most_common(1)[0][0] if kinds else "仕事"
    if not shift and len(kinds) < 2:
        # 身なり1件だけでは決めない
        return []
    words = sorted({m[0] for i in shift if (m := SHIFT.search(clues[i].value))})
    value = (f"{words[0]}のある" if words else "") + kind
    evidence = sorted({*shift, *(i for i, k in kinds.items() if k == kind)})
    return [Conclusion("R10", "occupation", value, evidence, "シフトの言葉と身なり")]


def infer(clues: Sequence[Clue], posts: Sequence[Post], gaz: Gazetteer) -> list[Conclusion]:
    """すべてのルールを順に当てはめる。R1・R5・R7 は R4 の、R2 は R1 の結論を使う。"""
    r4 = rule_r4(clues, gaz)
    r5 = rule_r5(clues, gaz, r4)
    r1 = rule_r1(clues, gaz, [*r4, *r5])
    return [
        *r4,
        *r5,
        *r1,
        *rule_r6(clues, gaz),
        *rule_r2(clues, posts, r1),
        *rule_r3(clues, posts),
        *rule_r7(clues, posts, gaz, r4),
        *rule_r8(clues),
        *rule_r9(clues, posts),
        *rule_r10(clues),
    ]


POSTAL_IN_TEXT = re.compile(r"(\d{3})-?(\d{4})")
BLOCK_IN_ADDRESS = re.compile(r"[0-9０-９一二三四五六七八九十]+丁目")
BIRTHDAY = re.compile(r"誕生日|歳になりました|バースデー|birthday", re.IGNORECASE)
ALCOHOL = re.compile(r"🍺|🍻|お酒|ビール|酒|飲める|解禁|堂々と")
SHIFT = re.compile(r"夜勤|早番|遅番|日勤|シフト")
# 身なり → 仕事の種類
OUTFITS = [
    (r"作業靴|安全靴|作業着|ヘルメット|つなぎ", "現場仕事"),
    (r"白衣|ナース|スクラブ", "医療の仕事"),
    (r"エプロン|コックコート", "接客・調理の仕事"),
]
BURNABLE = {"燃やす", "燃える", "可燃"}
GARBAGE_KINDS = re.compile(
    r"燃やさない|燃えない|不燃|プラスチック|プラ|資源|びん|缶|ペット|古紙|燃やす|燃える|可燃"
)
COLORS = "青緑黄赤白黒紫橙桃茶"


def _matching_bags(value: str, gaz: Gazetteer) -> list[TrashBag]:
    """品物の特徴（色・容量・枚数・値段）が全部合う指定ゴミ袋。特徴が2つ未満なら空。"""
    features: dict[str, Any] = {}
    if color := next((ch for ch in COLORS if ch in value), None):
        features["color"] = color
    for key, pattern in (
        ("liters", r"(\d+)\s*(?:L|ℓ|リットル)"),
        ("count", r"(\d+)\s*枚"),
        ("price", r"(\d[\d,]*)\s*円"),
    ):
        if m := re.search(pattern, value):
            features[key] = int(m[1].replace(",", ""))
    if len(features) < 2:
        return []
    return [
        b for b in gaz.knowledge.trash_bags if all(getattr(b, k) == v for k, v in features.items())
    ]


def _burnable_days(value: str) -> set[str]:
    """掲示の文字から、燃やすごみの曜日（毎週のもの）。"""
    marks = list(GARBAGE_KINDS.finditer(value))
    days: set[str] = set()
    for n, m in enumerate(marks):
        if m[0] not in BURNABLE:
            continue
        end = marks[n + 1].start() if n + 1 < len(marks) else len(value)
        segment = re.sub(r"第[0-9０-９・,、]+", "", value[m.end() : end])
        days |= {d for d in segment if d in WEEKDAYS}
    return days


def _mentioned_stations(value: str, gaz: Gazetteer) -> set[str]:
    """「八王子駅前店」のように「〇〇駅」と書かれた駅名。いちばん長く合う名前を使う。"""
    names: set[str] = set()
    for m in re.finditer(r"([^\s「」『』（）()・、。:：/]+?)駅", value):
        word = m[1]
        for k in range(len(word)):
            if hits := gaz.station_names(word[k:]):
                names |= hits
                break
    return names


def _clean_name(value: str) -> str:
    """敬称・読めない字（x）・お祝いの言葉などを落とした名前。"""
    name = re.sub(r"[（(].*?[)）]", "", value)
    name = re.sub(r"happy\s*birthday|hbd|dear", "", name, flags=re.IGNORECASE)
    name = re.sub(r"(おめ|おめでとう|お誕生日|誕生日|ありがとう|へ|より).*$", "", name)
    name = re.sub(r"(様|さま|さん|くん|君|ちゃん|氏)$", "", name.strip())
    name = re.sub(r"x+", "", name)
    return re.sub(r"[\s!！〜~、。]", "", name)


def _hiragana(text: str) -> str:
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


def _town_name(town: str) -> str:
    return re.sub(r"（.*）$", "", town)


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
