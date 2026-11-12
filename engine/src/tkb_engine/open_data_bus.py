"""国土数値情報のバス停留所（令和4年度版）を「X は Y にある」の知識として使う、居住地域の経路。

経路の形は避難所（open_data.shelter_home_facts）と同じで、次がそろったときだけ推定する。
- 本人との関係：ある投稿（またはプロフィール文）に「家の前のバス停、X」「最寄りのバス停は X」
  「毎朝 X バス停からバスに乗る」などがある
- 橋渡し：別の投稿の手がかり（ランドマーク・地名・生活の決まり・掲示）の値の先頭に同じ X がある
- 値：同じ名前のバス停は多いので、2つの投稿と手がかりに書かれた事業者名（「都営バス」など）か
  区市町村名で、バス停の区市町村が1つに絞れたときだけ使う
"""

import re
from collections.abc import Sequence

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.cross_post_facts import CrossPostFact, FactRole, forbidden_context
from tkb_engine.gazetteer import Gazetteer

# 名前が後ろにあるもの（「家の前のバス停、X」「最寄りのバス停は X」）
OWNER_STOP_RE = re.compile(
    r"(?:(?:自宅|家|うち)の?(?:すぐ)?(?:前|近く|目の前|最寄り)|最寄り)の?(?:バス停|停留所)"
    r"(?:は|の|が|、|:|：|「|\s)*"
)
# 名前が前にあるもの（「毎朝 X バス停からバスに乗る」）。同じ文に「毎朝」などが要る
DAILY_RIDE_RE = re.compile(r"(?:バス停|停留所)?から(?:バス|乗)")
DAILY_WORD_RE = re.compile(r"毎朝|毎日|毎晩|いつも")
SENTENCE_RE = re.compile(r"[^。！？!?\n]+")
HEAD_BREAK_RE = re.compile(r"[\s、。「『:：]|バス")
BRIDGE_CLUE_TYPES = frozenset(
    {ClueType.LANDMARK, ClueType.PLACE_TEXT, ClueType.ROUTINE_TEXT, ClueType.NOTICE}
)
OWNER_RELATION_CONFIDENCE = 0.65
OPEN_DATA_CONFIDENCE = 0.9
MAX_NAME_LENGTH = 20

# 事業者名の、ふだんの呼び方（表の事業者名 → 投稿に出てきそうな書き方）。
# 自治体の名前（「東京都」「横浜市」）は住所にも出てくるので、そのままでは合わせない
OPERATOR_ALIASES: dict[str, tuple[str, ...]] = {
    "東京都": ("都営バス", "都バス"),
    "横浜市": ("横浜市営バス", "横浜市バス", "市営バス"),
    "川崎市": ("川崎市営バス", "川崎市バス", "市営バス"),
    "神奈川中央交通": ("神奈中",),
    "京浜急行バス": ("京急バス",),
}
MUNICIPAL_OPERATORS = frozenset({"東京都", "横浜市", "川崎市"})

BUS_STOP_CITATION = (
    "出典：「国土数値情報（バス停留所データ）」（国土交通省）を加工して作成。"
    "令和4年度（2022年8月ごろ）時点のデータで、今と違う場合があります"
)


def bus_stop_home_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    owner_profile_text: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    """バス停の名前を橋渡しにした、居住地域の経路の材料。表がなければ空。"""
    if not gazetteer.bus_stops:
        return []
    anchors: list[tuple[str | None, str, str]] = [(p.post_id, p.text, "post_text") for p in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    facts: list[CrossPostFact] = []
    for anchor_post_id, text, source in anchors:
        if forbidden_context(text):
            continue
        for excerpt, name, rows in _owner_stops(text, gazetteer):
            bridge_id = f"home:bus:{name}"
            bridges = _bridge_facts(posts, clues, anchor_post_id, name, bridge_id, gazetteer)
            context = _context(text, bridges, posts, clues)
            located = _locate(rows, context)
            if located is None:
                continue
            city, operator = located
            facts.append(
                CrossPostFact(
                    anchor_post_id,
                    None,
                    FactRole.OWNER_RELATION,
                    name,
                    OWNER_RELATION_CONFIDENCE,
                    bridge_id,
                    True,
                    excerpt=excerpt,
                    source=source,
                )
            )
            facts.append(
                CrossPostFact(
                    None,
                    None,
                    FactRole.SPECIFIC_VALUE,
                    city,
                    OPEN_DATA_CONFIDENCE,
                    bridge_id,
                    excerpt=f"{name}（{operator}）は{city}にあるバス停（{BUS_STOP_CITATION}）",
                    source="open_data",
                )
            )
            facts.extend(bridges)
    return facts


def _owner_stops(text: str, gazetteer: Gazetteer) -> list[tuple[str, str, list[dict[str, object]]]]:
    """(抜き出した文, バス停名, その名前の行)。"""
    found: dict[str, tuple[str, list[dict[str, object]]]] = {}
    for match in OWNER_STOP_RE.finditer(text):
        window = text[match.end() : match.end() + MAX_NAME_LENGTH]
        for name, rows in gazetteer.bus_stops_named_at(window).items():
            found.setdefault(name, (match.group(0) + name, rows))
    for sentence in SENTENCE_RE.findall(text):
        if not DAILY_WORD_RE.search(sentence):
            continue
        for match in DAILY_RIDE_RE.finditer(sentence):
            head = re.split(r"[\s、]", sentence[: match.start()])[-1][-MAX_NAME_LENGTH:]
            for start in range(len(head)):
                named = gazetteer.bus_stops_named_at(head[start:])
                name = next(iter(named), "")
                if name and head[start:].startswith(name):
                    found.setdefault(name, (head[start:] + match.group(0), named[name]))
                    break
    return [(excerpt, name, rows) for name, (excerpt, rows) in found.items()]


def _heads(value: str) -> list[str]:
    """値の先頭と、空白・読点・「バス」のあとの位置（「都営バス 根津一丁目」→「根津一丁目」）。"""
    heads = [value]
    heads += [value[m.end() :].lstrip("のはが 　") for m in HEAD_BREAK_RE.finditer(value)]
    return [h for h in heads if h]


def _bridge_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    anchor_post_id: str | None,
    name: str,
    bridge_id: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    text_by_post = {p.post_id: p.text for p in posts}
    facts = []
    for index, clue in enumerate(clues):
        if (
            clue.post_id == anchor_post_id
            or clue.post_id not in text_by_post
            or clue.type not in BRIDGE_CLUE_TYPES
            or forbidden_context(text_by_post[clue.post_id])
            or not any(name in gazetteer.bus_stops_named_at(h) for h in _heads(clue.value))
        ):
            continue
        facts.append(
            CrossPostFact(
                clue.post_id,
                index,
                FactRole.BRIDGE,
                name,
                clue.confidence,
                bridge_id,
                excerpt=clue.value,
            )
        )
    return facts


def _context(
    anchor_text: str, bridges: list[CrossPostFact], posts: Sequence[Post], clues: Sequence[Clue]
) -> str:
    """事業者名と区市町村名を探す文字：関係を示す投稿と、橋渡しの投稿の本文と手がかり。"""
    bridge_posts = {f.post_id for f in bridges}
    texts = [anchor_text]
    texts += [p.text for p in posts if p.post_id in bridge_posts]
    texts += [c.value for c in clues if c.post_id in bridge_posts]
    return "\n".join(texts)


def _locate(rows: list[dict[str, object]], context: str) -> tuple[str, str] | None:
    """事業者名か区市町村名で絞った (区市町村, 事業者名)。1つに決まらなければ None。"""
    mentioned = {
        city
        for row in rows
        for city in _cities(row)
        if city in context or re.sub(r"^.+?郡", "", city) in context
    }
    cities: set[str] = set()
    operators: set[str] = set()
    for row in rows:
        operator = _operator_name(str(row.get("operator") or ""))
        row_cities = set(_cities(row))
        if mentioned & row_cities:
            cities |= mentioned & row_cities
        elif _operator_mentioned(operator, context):
            cities |= row_cities
        else:
            continue
        operators.add(OPERATOR_ALIASES.get(operator, (operator,))[0])
    if len(cities) != 1:
        return None
    return next(iter(cities)), "・".join(sorted(operators))


def _cities(row: dict[str, object]) -> list[str]:
    value = row.get("cities") or []
    return [str(c) for c in value if c] if isinstance(value, list) else []


def _operator_name(operator: str) -> str:
    return re.sub(r"[（(]株[)）]|株式会社|[（(]有[)）]|有限会社", "", operator).strip()


def _operator_mentioned(operator: str, context: str) -> bool:
    aliases = list(OPERATOR_ALIASES.get(operator, ()))
    if operator not in MUNICIPAL_OPERATORS and len(operator) >= 2:
        aliases.append(operator)
    return any(alias in context for alias in aliases)
