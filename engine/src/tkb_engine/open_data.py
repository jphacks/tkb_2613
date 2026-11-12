"""公的な公開データ（事前に取得した手元の表）を「X は Y」の知識として使う推定経路。

公開データは本人についての事実ではない。本人との関係は、投稿に明示された言い回し
（「自宅近くの X」など）でだけ決め、公開データは「X は Y にある」という一般的な知識にだけ使う。
診断のたびに外部へ問い合わせることはしない。

経路の形は cross_post の居住地域と同じで、次の3つが揃ったときだけ推定する。
- 本人との関係：ある投稿（またはプロフィール文）に「自宅近くの X」「近所の X」などがある
- 橋渡し：別の投稿の手がかり（ランドマーク・掲示・地名）の値に X が出てくる
- 値：公開データの表で X が1つの区市町村だけにある（同じ名前が2つ以上の区市町村にあれば使わない）
"""

import re
from collections.abc import Sequence

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.cross_post_facts import CrossPostFact, FactRole, forbidden_context
from tkb_engine.gazetteer import Gazetteer

# 本人の住まいとの関係を明示する言い回し。この後ろ（文の終わりまで）に施設名がある
OWNER_NEAR_HOME_RE = re.compile(
    r"(?:(?:自宅|家|うち)の?(?:すぐ)?(?:近く|近所|目の前|前|そば)|近所)の?"
)
# 言い回しの後ろで、抜き出して根拠に見せる長さ
OWNER_NEAR_HOME_WINDOW = 40
SENTENCE_END_RE = re.compile(r"[。！？!?\n]")
BRIDGE_CLUE_TYPES = frozenset({ClueType.LANDMARK, ClueType.NOTICE, ClueType.PLACE_TEXT})

# 根拠の確からしさ。言い回しの判定は cross_post の居住地域と同じ控えめな値、
# 表の対応（施設名 → 区市町村）は公的な表なので高めにする。経路の確からしさは弱いほうになる
OWNER_RELATION_CONFIDENCE = 0.65
OPEN_DATA_CONFIDENCE = 0.9

SHELTER_CITATION = (
    "出典：国土地理院「指定緊急避難場所・指定避難所データ」を加工して作成。"
    "最新でない場合や未掲載の場合があります（最新の状況は各市町村にご確認ください）"
)


def shelter_home_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    owner_profile_text: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    """避難所の名前を橋渡しにした、居住地域の経路の材料。表がなければ空。"""
    if not gazetteer.shelters:
        return []
    anchors: list[tuple[str | None, str, str]] = [(p.post_id, p.text, "post_text") for p in posts]
    if owner_profile_text.strip():
        anchors.append((None, owner_profile_text, "profile_text"))
    facts: list[CrossPostFact] = []
    for anchor_post_id, text, source in anchors:
        if forbidden_context(text):
            continue
        for excerpt, name, rows in _named_near_home(text, gazetteer):
            cities = {str(r["city"]) for r in rows}
            if len(cities) != 1:
                continue  # 同じ名前の施設が別の区市町村にもある
            city = next(iter(cities))
            bridge_id = f"home:shelter:{name}"
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
                    excerpt=f"{name}は{city}の{_kind(rows)}（{SHELTER_CITATION}）",
                    source="open_data",
                )
            )
            facts.extend(_bridge_facts(posts, clues, anchor_post_id, name, bridge_id, gazetteer))
    return facts


def _named_near_home(
    text: str, gazetteer: Gazetteer
) -> list[tuple[str, str, list[dict[str, object]]]]:
    """(抜き出した文, 施設名, その名前の行)。言い回しのすぐ後ろに書かれた施設名だけ。"""
    found: dict[str, tuple[str, list[dict[str, object]]]] = {}
    for match in OWNER_NEAR_HOME_RE.finditer(text):
        window = text[match.end() : match.end() + OWNER_NEAR_HOME_WINDOW]
        window = SENTENCE_END_RE.split(window, maxsplit=1)[0]
        for name, rows in gazetteer.shelters_named_at(window).items():
            found.setdefault(name, (match.group(0) + window, rows))
    return [(excerpt, name, rows) for name, (excerpt, rows) in found.items()]


def _bridge_facts(
    posts: Sequence[Post],
    clues: Sequence[Clue],
    anchor_post_id: str | None,
    name: str,
    bridge_id: str,
    gazetteer: Gazetteer,
) -> list[CrossPostFact]:
    """別の投稿の手がかり（ランドマーク・掲示・地名）に、同じ施設名が出てくるもの。"""
    text_by_post = {p.post_id: p.text for p in posts}
    facts = []
    for index, clue in enumerate(clues):
        if (
            clue.post_id == anchor_post_id
            or clue.post_id not in text_by_post
            or clue.type not in BRIDGE_CLUE_TYPES
            or forbidden_context(text_by_post[clue.post_id])
            or name not in gazetteer.shelters_named_at(clue.value)
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


def _kind(rows: list[dict[str, object]]) -> str:
    kinds = {k for r in rows for k in str(r.get("kind") or "").split("・") if k}
    return "・".join(sorted(kinds, reverse=True)) or "避難所"
