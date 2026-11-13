"""子どもの学校（child_school）の推定の材料（事実）を作る。

居住地域と同じく、本人との関係と学校名が別々の投稿にはっきり書かれ、同じ橋渡しでつながる
ときだけ推定する（組み立ては cross_post.infer_cross_post_claim）。
- 関係の投稿：「娘の小学校のひまわり祭り」のように、本人の子どもの学校の X（橋渡し）
- 値の投稿：別の投稿の「ひまわり祭りは〇〇小学校の行事」と、その投稿の本文の手がかり org_text
- 制服・校舎の写真だけ、学校名だけの投稿では推定しない
- 「友達の娘」のような他人の子ども、受験・見学・卒業などの、今は通っていない文脈は使わない
- 学校名は国土数値情報の小学校区・中学校区の表で引き、学校が1つに決まるときだけ値にする。
  表にない学校（私立・1都3県の外など）は、同名の学校がないかを確かめられないので使わない
"""

import re
import unicodedata

from tkb_common.schemas import Clue, ClueType, Post
from tkb_engine.cross_post_facts import (
    CrossPostFact,
    FactRole,
    forbidden_context,
    is_distinctive_bridge,
    matching_text_clue,
    normalize_bridge,
)
from tkb_engine.gazetteer import Gazetteer

BRIDGE_PREFIX = "child_school:"
ANCHOR_CONFIDENCE = 0.65  # 仮のルールの強さ。較正した確率ではない
_RELATION = r"うちの子|息子|娘|長男|次男|三男|長女|次女|三女"
ANCHOR_RE = re.compile(
    rf"(?P<relation>{_RELATION})(?:が通う|の通う|が通ってる|の通ってる|の)(?:小学校|中学校|学校)の"
    # 橋渡しは、次の助詞か句読点まで（「ひまわり祭りで踊った」→「ひまわり祭り」）
    r"(?P<bridge>[^\s、。！？!?「」]+?)(?=[、。！？!?\sでにがはをもへとの]|$)"
)
VALUE_RE = (
    r"{bridge}(?:は|が|って)(?P<value>[^\s、。！？!?「」]+?(?:小学校|中学校|小|中))"
    r"(?=[のでにがはへ、。！？!?\s]|$)"
)
# 「〜の娘」のうち、本人の子どもを指すもの
OWNER_POSSESSIVES = ("うちの", "私の", "わたしの", "僕の", "ぼくの", "俺の", "自分の", "我が家の")
# まだ通っていない・もう通っていない文脈
NOT_ATTENDING_RE = re.compile(r"受験|志望|説明会|体験入学|卒業|母校|転校前|昔")
# 学校の行事・場所の一般の名前。どの学校にもあるので橋渡しにしない
GENERIC_BRIDGES = frozenset(
    {
        "運動会",
        "学芸会",
        "文化祭",
        "発表会",
        "音楽会",
        "授業参観",
        "参観日",
        "保護者会",
        "懇談会",
        "入学式",
        "卒業式",
        "始業式",
        "終業式",
        "遠足",
        "給食",
        "宿題",
        "先生",
        "担任",
        "クラス",
        "校庭",
        "体育館",
        "プール",
        "学童",
        "pta",
    }
)
# 「夏祭り」のように、前に付く名前が短いものも一般の名前とみなす
EVENT_SUFFIXES = ("祭り", "まつり", "祭", "大会", "会", "式")


def child_school_facts(
    posts: list[Post], clues: list[Clue], gazetteer: Gazetteer
) -> list[CrossPostFact]:
    """関係・値・橋渡しの事実。学区の表がなければ空。"""
    if not gazetteer.school_districts:
        return []
    facts: list[CrossPostFact] = []
    for anchor_post in posts:
        text = unicodedata.normalize("NFKC", anchor_post.text)
        if not _usable(text):
            continue
        for match in ANCHOR_RE.finditer(text):
            if not _owner_relation(text, match.start()):
                continue
            bridge_text = match.group("bridge")
            if not _named_bridge(bridge_text):
                continue
            bridge_id = BRIDGE_PREFIX + normalize_bridge(bridge_text)
            facts.append(
                CrossPostFact(
                    anchor_post.post_id,
                    None,
                    FactRole.OWNER_RELATION,
                    bridge_text,
                    ANCHOR_CONFIDENCE,
                    bridge_id,
                    True,
                    excerpt=match.group(0),
                )
            )
            facts.extend(
                _other_post_facts(posts, clues, gazetteer, anchor_post, bridge_text, bridge_id)
            )
    return facts


def _other_post_facts(
    posts: list[Post],
    clues: list[Clue],
    gazetteer: Gazetteer,
    anchor_post: Post,
    bridge_text: str,
    bridge_id: str,
) -> list[CrossPostFact]:
    facts: list[CrossPostFact] = []
    value_re = re.compile(VALUE_RE.format(bridge=re.escape(bridge_text)))
    for post in posts:
        text = unicodedata.normalize("NFKC", post.text)
        if post.post_id == anchor_post.post_id or not _usable(text) or bridge_text not in text:
            continue
        facts.append(
            CrossPostFact(
                post.post_id,
                None,
                FactRole.BRIDGE,
                bridge_text,
                ANCHOR_CONFIDENCE,
                bridge_id,
                excerpt=bridge_text,
            )
        )
        for match in value_re.finditer(text):
            written = match.group("value")
            school = _unique_school(gazetteer, written)
            typed = matching_text_clue(clues, post.post_id, written, ClueType.ORG_TEXT)
            if school is None or typed is None:
                continue
            clue_index, clue = typed
            facts.append(
                CrossPostFact(
                    post.post_id,
                    clue_index,
                    FactRole.SPECIFIC_VALUE,
                    school,
                    clue.confidence,
                    bridge_id,
                    excerpt=match.group(0),
                )
            )
    return facts


def _usable(text: str) -> bool:
    return not forbidden_context(text) and not NOT_ATTENDING_RE.search(text)


def _owner_relation(text: str, start: int) -> bool:
    """関係の語の直前が「〜の」なら、本人の子どものときだけ（「友達の娘」は使わない）。"""
    before = text[:start]
    if text[start:].startswith("うちの子") or not before.endswith("の"):
        return True
    return before.endswith(OWNER_POSSESSIVES)


def _named_bridge(bridge: str) -> bool:
    key = normalize_bridge(bridge)
    if key in GENERIC_BRIDGES or not is_distinctive_bridge(bridge):
        return False
    for suffix in EVENT_SUFFIXES:
        if key.endswith(suffix):
            return len(key) - len(suffix) >= 2
    return True


def _unique_school(gazetteer: Gazetteer, name: str) -> str | None:
    """学区の表で学校が1つに決まれば、表の学校名。同名の学校が2つ以上の区市町村にあれば None。
    （同じ区市町村の同じ名前の行は、1つの学校の学区が分かれたものとみなす）"""
    rows = gazetteer.districts_of_school(name)
    schools = {(str(r.get("city") or ""), str(r.get("kind") or "")) for r in rows}
    if len(schools) != 1:
        return None
    return str(rows[0]["name"])
