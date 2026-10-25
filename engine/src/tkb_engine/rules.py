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
- R4 市区町村：指定ゴミ袋（local_item）の容量と1枚の値段で候補を絞り、「〇〇まで遠い」のような
  距離の手がかりを駅の位置と照らして1つに決める。掲示・品物に書かれた市区町村名も使う
- R5 収集地区：R4 の市区町村で、集積所の掲示（notice）の燃やすごみの曜日が合う収集地区。
  郵便物・住所表示の町名でさらに絞る
- R6 区画：郵便物のカスタマバーコードの中身（code）や住所表示（address_text）の郵便番号・町名と番地
- R7 通学先：学校の名前（学校コードの表）が出てくればその学校。なければ「大学」と「〇限」の
  本文を、R4 の市区町村にある大学の時間割と照らす
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
from zoneinfo import ZoneInfo

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.gazetteer import CollectionArea, Gazetteer, TrashBag, distance_km

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

    area は R4・R5 の結論（先頭が R4 の市区町村）。住所・郵便番号の手がかりがないとき、
    先頭の市区町村で駅を絞り、その根拠も駅の根拠に入れる。
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
        area_evidence = set(area[0].clue_indices)
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


def rule_r4(clues: Sequence[Clue], gaz: Gazetteer, posts: Sequence[Post] = ()) -> list[Conclusion]:
    """R4 市区町村（home_city）。手がかりごとに市区町村の候補を絞り、1つに決まれば結論にする。

    - 指定ゴミ袋（local_item）：容量と1枚の値段が合う市区町村（ふつうは複数）
    - 掲示・品物に書かれた市区町村名
    - 距離の手がかり：「中野まで遠くてだるい」「新宿まですぐ」のような、駅名と遠い・近いの組。
      候補の市区町村から、その駅までの距離が合わないものを外す。これ単体では市区町村は決まらない
    """
    texts = {p.post_id: p.text for p in posts}
    candidates: set[str] | None = None
    evidence: set[int] = set()
    notes: list[str] = []
    for i, c in enumerate(clues):
        found: set[str] = set()
        if c.type is ClueType.LOCAL_ITEM and (bags := _matching_bags(c.value, gaz)):
            found = {b.city for b in bags}
            notes.append(
                f"指定ゴミ袋（{bags[0].liters}L 1枚{bags[0].price:g}円）で{_cities(found)}"
            )
        if c.type in {ClueType.LOCAL_ITEM, ClueType.NOTICE} and (named := gaz.cities_in(c.value)):
            found = named
            notes.append(f"{_cities(named)}の文字")
        if not found:
            continue
        candidates = found if candidates is None else candidates & found
        evidence.add(i)
    if not candidates:
        # 手がかりがないか、市区町村が食い違う
        return []
    for i, station, far in _distance_hints(clues, gaz, texts):
        kept, notes_here = _by_distance(candidates, station, far, gaz)
        if kept and kept != candidates:
            candidates = kept
            evidence.add(i)
            notes.append(notes_here)
    if len(candidates) != 1:
        return []
    city = next(iter(candidates))
    return [Conclusion("R4", "home_city", city, sorted(evidence), "。".join(notes))]


# 距離の手がかり：遠い・近いの言葉と、遠い・近いとみなす距離（市区町村の駅の中心から、km）
FAR_WORDS = re.compile(r"遠い|遠くて|遠すぎ|遠いし|時間かかる|乗り換え多")
NEAR_WORDS = re.compile(r"近い|近くて|すぐ着|すぐ行ける|歩いて行ける|チャリで行ける")
FAR_KM = 20.0
NEAR_KM = 12.0
DISTANCE_TYPES = {ClueType.PLACE_TEXT, ClueType.ROUTINE_TEXT}


def _distance_hints(
    clues: Sequence[Clue], gaz: Gazetteer, texts: dict[str, str]
) -> list[tuple[int, str, bool]]:
    """(手がかりの番号, 駅名, 遠いなら True)。遠い・近いは手がかりと投稿の本文から読む。"""
    hints = []
    for i, c in enumerate(clues):
        if c.type not in DISTANCE_TYPES:
            continue
        text = c.value + " " + texts.get(c.post_id, "")
        far, near = FAR_WORDS.search(text), NEAR_WORDS.search(text)
        if bool(far) == bool(near):
            continue
        for station in gaz.stations_named_in(c.value):
            hints.append((i, station, bool(far)))
    return hints


def _by_distance(
    candidates: set[str], station: str, far: bool, gaz: Gazetteer
) -> tuple[set[str], str]:
    """駅までの距離が遠い・近いに合う候補と、そのメモ。距離が測れなければ候補をそのまま返す。"""
    point = gaz.station_point(station)
    if point is None:
        return candidates, ""
    distances = {}
    for city in candidates:
        center = gaz.city_point(city)
        if center is None:
            return candidates, ""
        distances[city] = distance_km(center, point)
    kept = {c for c, d in distances.items() if (d > FAR_KM if far else d < NEAR_KM)}
    word = "遠い" if far else "近い"
    detail = "、".join(
        f"{c}から約{d:.0f}km" for c, d in sorted(distances.items(), key=lambda x: x[1])
    )
    return kept, f"{station}まで{word}（{detail}）ので{_cities(kept)}"


def _cities(cities: set[str]) -> str:
    return "・".join(sorted(cities))


def rule_r5(clues: Sequence[Clue], gaz: Gazetteer, r4: list[Conclusion]) -> list[Conclusion]:
    """R5 収集地区（home_district）：集積所の掲示の燃やすごみの曜日と、住所の町名。

    曜日が分からない地区は、どの曜日にも合うとみなす（表が埋まるほど絞れる）。
    地区が1つに決まらなければ「燃やすごみが月・木の地区」までにする。
    """
    if not r4:
        return []
    city = r4[0].value
    in_city = [a for a in gaz.knowledge.collection_areas if a.city == city]
    for i, c in enumerate(clues):
        if c.type is not ClueType.NOTICE or not (days := _burnable_days(c.value)):
            continue
        label = "・".join(d for d in WEEKDAYS if d in days)
        candidates = [a for a in in_city if not a.burnable_days or set(a.burnable_days) == days]
        evidence = {i, *r4[0].clue_indices}
        note = f"集積所の燃やすごみの曜日（{label}）が合う地区"
        # 郵便物や住所表示の町名で、候補の地区をさらに絞る
        for j, town in _home_towns(clues, gaz, city):
            narrowed = [a for a in candidates if _has_town(a, town)]
            if narrowed:
                candidates = narrowed
                evidence.add(j)
                note += f"。町名（{town}）で絞った"
                break
        if len(candidates) == 1:
            value = f"{city} {candidates[0].area}"
        elif candidates:
            value = f"{city} 燃やすごみが{label}の地区"
        else:
            continue
        return [Conclusion("R5", "home_district", value, sorted(evidence), note)]
    return []


def _home_towns(clues: Sequence[Clue], gaz: Gazetteer, city: str) -> list[tuple[int, str]]:
    """郵便物のカスタマバーコードと住所表示から読める、その市区町村の町名。"""
    towns = []
    for i, c in enumerate(clues):
        if c.type is ClueType.CODE and _is_customer_barcode(c.value):
            m = POSTAL_IN_TEXT.search(c.value)
            rows = gaz.postal_rows(m[1] + m[2]) if m else []
            towns += [(i, _town_name(r["town"])) for r in rows if r["city"] == city]
        elif c.type is ClueType.ADDRESS_TEXT and city in c.value:
            _, found = gaz.area(c)
            towns += [(i, t) for t in found]
    return towns


def _has_town(area: CollectionArea, town: str) -> bool:
    """地区の町名の書き方（「子安町1・3・4丁目」「館町（館ヶ丘団地）」など）の町の部分が合うか。"""
    return any(re.split(r"[0-9０-９（(]", t, maxsplit=1)[0] == town for t in area.towns)


def _is_customer_barcode(value: str) -> bool:
    return "カスタマバーコード" in value or "〒" in value


def rule_r6(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    """R6 区画（home_block）：郵便番号・町名と番地。郵便物のバーコードの中身や住所表示から。"""
    for i, c in enumerate(clues):
        if c.type not in {ClueType.CODE, ClueType.ADDRESS_TEXT}:
            continue
        # 住所が入っているのはカスタマバーコード（郵便物）だけ。宅配伝票などの番号は郵便番号と
        # 見分けがつかないので使わない
        if (
            c.type is ClueType.CODE
            and _is_customer_barcode(c.value)
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
    """R7 通学先（school）。

    1. 学校の名前（学校コードの表にある大学・高校など）が写真や本文に出てくれば、その学校
    2. なければ「大学」と「〇限」の投稿を、R4 の市区町村にある大学の時間割と照らす。
       時間割の分からない大学は候補に残し、1校に決まらなければ「〇〇市にある大学」までにする
    """
    named = _named_school(clues, gaz)
    if named:
        return named
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
    timetables = {u.name: u.periods for u in gaz.knowledge.universities}
    names = {s["name"] for s in gaz.schools if s["kind"] == "大学" and s["city"] == city}
    names |= {u.name for u in gaz.knowledge.universities if u.city == city}
    candidates = sorted(
        n
        for n in names
        if n not in timetables
        or all(
            k in timetables[n] and timetables[n][k][0] - R7_EARLY_HOURS <= t <= timetables[n][k][1]
            for _, k, t in periods
        )
    )
    if not candidates:
        return []
    walk = any("歩いて" in texts[i].value or "徒歩" in texts[i].value for i in college)
    if len(candidates) == 1:
        campus = next((u.campus for u in gaz.knowledge.universities if u.name == candidates[0]), "")
        value = f"{candidates[0]} {campus}".strip()
        note = f"{city}の大学で時間割が合うのはここだけ"
    else:
        value = f"{city}にある大学（{len(candidates)}校のどれか）"
        note = "「大学」と時限の投稿。候補：" + "・".join(candidates[:5])
    value += "（歩いて通える所に住んでいる）" if walk else ""
    evidence = sorted({*college, *(i for i, _, _ in periods), *r4[0].clue_indices})
    return [Conclusion("R7", "school", value, evidence, note)]


# 学校の名前を探す手がかり
SCHOOL_NAME_TYPES = {
    ClueType.ORG_TEXT,
    ClueType.UNIFORM,
    ClueType.NOTICE,
    ClueType.PLACE_TEXT,
    ClueType.LANDMARK,
    ClueType.ROUTINE_TEXT,
    ClueType.REFLECTION,
}


def _named_school(clues: Sequence[Clue], gaz: Gazetteer) -> list[Conclusion]:
    votes: dict[str, list[int]] = {}
    kinds: dict[str, str] = {}
    for i, c in enumerate(clues):
        if c.type not in SCHOOL_NAME_TYPES:
            continue
        found = gaz.schools_named_in(c.value)
        if len(found) == 1:
            votes.setdefault(found[0]["name"], []).append(i)
            kinds[found[0]["name"]] = found[0]["city"]
    if len(votes) != 1:
        return []
    name, indices = next(iter(votes.items()))
    return [Conclusion("R7", "school", f"{name}（{kinds[name]}）", indices, "学校の名前")]


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
    r4 = rule_r4(clues, gaz, posts)
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
# 1枚の値段の比べ方（「10枚 375円」は 37.5円で、表の 37円に合わせる）
BAG_PRICE_TOLERANCE = 0.6


def _matching_bags(value: str, gaz: Gazetteer) -> list[TrashBag]:
    """品物の容量と1枚の値段（色が分かる袋は色も）が合う指定ゴミ袋。

    値段は「10枚入り 750円」のような袋の束の値段から、1枚あたりにして比べる。
    """
    liters = re.search(r"(\d+)\s*(?:L|ℓ|リットル)", value)
    price = re.search(r"(\d[\d,]*)\s*円", value)
    if liters is None or price is None:
        return []
    count = re.search(r"(\d+)\s*枚", value)
    unit = int(price[1].replace(",", "")) / (int(count[1]) if count else 1)
    color = next((ch for ch in COLORS if ch in value), None)
    return [
        b
        for b in gaz.knowledge.trash_bags
        if b.liters == int(liters[1])
        and abs(b.price - unit) < BAG_PRICE_TOLERANCE
        and (not b.color or color is None or b.color == color)
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
