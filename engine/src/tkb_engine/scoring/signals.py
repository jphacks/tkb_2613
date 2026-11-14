"""投稿から、住まいの推定の層の材料（シグナル）を取り出す。

本人との関係が書かれた投稿だけを使う（設計書 3章）。
- 本文のシグナル：投稿の本文そのものを正規表現で読む（本文に文字列が実在する）。
  関係を示す言い回し（「部屋」「近所」「出し忘れた」など）が同じ文にあるときだけ
- 写真のシグナル：同じ投稿・同じ写真で、OCR と VLM の両方が同じ文字を読んだときだけ
読み取りの確からしさ（confidence）で重みは変えない。
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine.cross_post_facts import forbidden_context


class SignalKind(StrEnum):
    WALK_MINUTES = "walk_minutes"  # 層1
    LINE = "line"  # 層2
    BUS_STOP = "bus_stop"  # 層3
    SHELTER = "shelter"  # 層4
    TOWN = "town"  # 層5
    COLLECTION = "collection"  # 層6
    PLACE = "place"  # 層7
    AGE = "age"  # 層0・層8
    BIRTHDAY = "birthday"  # 層8


LAYER_OF = {
    SignalKind.AGE: 0,
    SignalKind.WALK_MINUTES: 1,
    SignalKind.LINE: 2,
    SignalKind.BUS_STOP: 3,
    SignalKind.SHELTER: 4,
    SignalKind.TOWN: 5,
    SignalKind.COLLECTION: 6,
    SignalKind.PLACE: 7,
    SignalKind.BIRTHDAY: 8,
}


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    post_id: str
    value: str
    excerpt: str
    # 写真のシグナルの根拠の手がかり（clues での番号）。本文のシグナルは空
    clue_indices: tuple[int, ...] = ()

    @property
    def layer(self) -> int:
        return LAYER_OF[self.kind]


SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?\n]?")
EXCERPT_MAX = 60

WALK_RE = re.compile(r"最寄り?(?:の)?駅?(?:まで|から)?(?:は)?(?:徒歩|歩いて)\s*(\d{1,2})\s*分")
HOME_WORDS = ("部屋", "家", "うち", "自宅", "住", "アパート", "マンション", "物件")
LINE_USE_WORDS = (
    "止ま",
    "遅れ",
    "遅延",
    "混ん",
    "乗",
    "使",
    "通勤",
    "通学",
    "歩いて",
    "最寄",
    "利用",
)
BUS_STOP_RE = re.compile(r"(?:家|うち|自宅)の(?:目の)?前のバス停(?:は|が|、|,|「)?\s*")
SHELTER_RE = re.compile(
    r"(?:近所|家の近く|うちの近く|自宅の近く|近く)の(.{2,30}?)(?:が|は|って)(?:指定)?避難所"
)
NEAR_HOME_WORDS = ("近所", "家の近く", "うちの近く", "自宅の近く", "家の前", "うちの前")
COLLECTION_RE = re.compile(
    r"(?:燃える|燃やす|可燃)(?:ゴミ|ごみ)[、,は]?\s*([月火水木金土日]{1,3})(?:曜日?)?"
)
COLLECTION_WORDS = ("出し忘れ", "出す", "出した", "出せ", "捨て", "ゴミの日", "ごみの日")
AGE_RE = re.compile(r"(?<!\d)(\d{2})歳")
NOT_SELF_BEFORE_AGE = (
    "娘",
    "息子",
    "子",
    "弟",
    "妹",
    "兄",
    "姉",
    "父",
    "母",
    "猫",
    "犬",
    "彼",
    "友",
)
BIRTHDAY_RE = re.compile(
    r"誕生日(?:が|は)?\s*(\d{1,2})月(\d{1,2})日|(\d{1,2})月(\d{1,2})日(?:が|は)?(?:誕生日|生まれ)"
)
PHOTO_TOWN_TYPES = frozenset(
    {ClueType.ADDRESS_TEXT, ClueType.PLACE_TEXT, ClueType.NOTICE, ClueType.LANDMARK}
)
TOWN_FRAGMENT_MIN = 2
AGE_MIN, AGE_MAX = 15, 99


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.findall(normalized(text)) if s.strip()]


def excerpt(sentence: str) -> str:
    return sentence if len(sentence) <= EXCERPT_MAX else sentence[: EXCERPT_MAX - 1] + "…"


def text_signals(
    post: Post,
    line_names: Iterable[str],
    bus_stop_names: Iterable[str],
) -> list[Signal]:
    """本文から読むシグナル（層7のよく行く場所は places.py で読む）。"""
    found: list[Signal] = []
    lines = sorted(set(line_names), key=len, reverse=True)
    stops = frozenset(bus_stop_names)
    for sentence in sentences(post.text):
        if forbidden_context(sentence):
            continue
        found.extend(_walk(post.post_id, sentence))
        found.extend(_lines(post.post_id, sentence, lines))
        found.extend(_bus_stop(post.post_id, sentence, stops))
        found.extend(_shelter(post.post_id, sentence))
        found.extend(_collection(post.post_id, sentence))
        found.extend(_age(post.post_id, sentence))
        found.extend(_birthday(post.post_id, sentence))
    return found


def _walk(post_id: str, sentence: str) -> list[Signal]:
    match = WALK_RE.search(sentence)
    if match is None or not any(w in sentence for w in HOME_WORDS):
        return []
    return [Signal(SignalKind.WALK_MINUTES, post_id, str(int(match.group(1))), excerpt(sentence))]


def _lines(post_id: str, sentence: str, lines: Sequence[str]) -> list[Signal]:
    if not any(w in sentence for w in LINE_USE_WORDS):
        return []
    found: list[Signal] = []
    rest = sentence
    for line in lines:
        if line in rest:
            found.append(Signal(SignalKind.LINE, post_id, line, excerpt(sentence)))
            rest = rest.replace(line, "")
    return found


def _bus_stop(post_id: str, sentence: str, stops: frozenset[str]) -> list[Signal]:
    match = BUS_STOP_RE.search(sentence)
    if match is None:
        return []
    window = sentence[match.end() :]
    for size in range(min(len(window), 20), 1, -1):
        name = window[:size]
        if name in stops:
            return [Signal(SignalKind.BUS_STOP, post_id, name, excerpt(sentence))]
    return []


def _shelter(post_id: str, sentence: str) -> list[Signal]:
    match = SHELTER_RE.search(sentence)
    if match is None:
        return []
    return [Signal(SignalKind.SHELTER, post_id, match.group(1).strip("「」 "), excerpt(sentence))]


def _collection(post_id: str, sentence: str) -> list[Signal]:
    match = COLLECTION_RE.search(sentence)
    if match is None or not any(w in sentence for w in COLLECTION_WORDS):
        return []
    return [Signal(SignalKind.COLLECTION, post_id, match.group(1), excerpt(sentence))]


def _age(post_id: str, sentence: str) -> list[Signal]:
    for match in AGE_RE.finditer(sentence):
        before = sentence[max(0, match.start() - 4) : match.start()]
        age = int(match.group(1))
        if AGE_MIN <= age <= AGE_MAX and not any(w in before for w in NOT_SELF_BEFORE_AGE):
            return [Signal(SignalKind.AGE, post_id, str(age), excerpt(sentence))]
    return []


def _birthday(post_id: str, sentence: str) -> list[Signal]:
    match = BIRTHDAY_RE.search(sentence)
    if match is None:
        return []
    month, day = (match.group(1), match.group(2)) if match.group(1) else match.group(3, 4)
    return [Signal(SignalKind.BIRTHDAY, post_id, f"{int(month)}月{int(day)}日", excerpt(sentence))]


def photo_town_signals(
    post: Post,
    clues: Sequence[Clue],
    indices: Sequence[int],
    town_names: Sequence[str],
) -> list[Signal]:
    """写真の町名の一部（電柱の住所の板など）。OCR と VLM が同じ文字を読み、近所の話のときだけ。

    indices は、clues の各手がかりの、診断の全手がかりでの番号。
    """
    text = normalized(post.text)
    if forbidden_context(text) or not any(w in text for w in NEAR_HOME_WORDS):
        return []
    photo = [
        (i, c)
        for i, c in zip(indices, clues, strict=True)
        if c.post_id == post.post_id and c.type in PHOTO_TOWN_TYPES and c.image_index is not None
    ]
    found: dict[str, Signal] = {}
    for i, ocr in photo:
        if ocr.source != ClueSource.OCR:
            continue
        for j, vlm in photo:
            if vlm.source != ClueSource.VLM or vlm.image_index != ocr.image_index:
                continue
            fragment = _common(ocr.value, vlm.value, town_names)
            if fragment is not None and fragment not in found:
                found[fragment] = Signal(
                    SignalKind.TOWN,
                    post.post_id,
                    fragment,
                    excerpt(sentences(post.text)[0] if post.text.strip() else ""),
                    (i, j),
                )
    return list(found.values())


def _common(a: str, b: str, town_names: Sequence[str]) -> str | None:
    """2つの読みの短いほうが長いほうに含まれ、町丁目の名前の一部なら、その文字。"""
    a, b = (normalized(a).replace(" ", ""), normalized(b).replace(" ", ""))
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < TOWN_FRAGMENT_MIN or short not in long:
        return None
    return short if any(short in name for name in town_names) else None
