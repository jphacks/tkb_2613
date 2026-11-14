import pytest

from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_engine.scoring.signals import (
    Signal,
    SignalKind,
    photo_town_signals,
    text_signals,
)

LINES = ["千代田線", "南北線", "山手線"]
STOPS = ["弥生二丁目", "根津駅前"]


def post(text: str, post_id: str = "at://did:plc:x/app.bsky.feed.post/1") -> Post:
    return Post(post_id=post_id, text=text, created_at="2026-11-01T08:00:00+09:00", images=[])


def kinds(text: str) -> list[tuple[SignalKind, str]]:
    return [(s.kind, s.value) for s in text_signals(post(text), LINES, STOPS)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("最寄り駅まで徒歩6分の部屋にして正解だった", [(SignalKind.WALK_MINUTES, "6")]),
        ("最寄り駅まで徒歩６分", []),  # 部屋・家の話がない
        ("千代田線、また止まってる…", [(SignalKind.LINE, "千代田線")]),
        ("南北線の駅も歩いて行けるの、地味に便利", [(SignalKind.LINE, "南北線")]),
        ("千代田線のポスターがかわいい", []),  # 使っている話がない
        ("家の前のバス停、根津駅前から乗る", [(SignalKind.BUS_STOP, "根津駅前")]),
        ("家の前のバス停、知らない名前", []),
        ("近所の根津小学校が避難所なの知らなかった", [(SignalKind.SHELTER, "根津小学校")]),
        ("燃えるゴミ、月木なのにまた出し忘れた", [(SignalKind.COLLECTION, "月木")]),
        ("燃えるゴミの袋を買った", []),
        ("22歳、いまだに自炊がうまくならない", [(SignalKind.AGE, "22")]),
        ("娘が12歳になった", []),
        ("弟は20歳になった", []),
        (
            "誕生日が4月14日だと、新学期のバタバタで毎年誰にも祝われない",
            [(SignalKind.BIRTHDAY, "4月14日")],
        ),
        ("4月14日生まれです", [(SignalKind.BIRTHDAY, "4月14日")]),
        ("近所の公民館に見学で行った。千代田線に乗った", [(SignalKind.LINE, "千代田線")]),
    ],
)
def test_text_signals(text: str, expected: list[tuple[SignalKind, str]]) -> None:
    assert kinds(text) == expected


def test_text_signals_skip_visits() -> None:
    assert kinds("見学で千代田線に乗った") == []


def test_signal_layer_numbers() -> None:
    assert Signal(SignalKind.WALK_MINUTES, "p", "6", "").layer == 1
    assert Signal(SignalKind.PLACE, "p", "x", "").layer == 7
    assert Signal(SignalKind.BIRTHDAY, "p", "x", "").layer == 8


def photo_clue(source: ClueSource, value: str, image_index: int = 0) -> Clue:
    return Clue(
        post_id="at://did:plc:x/app.bsky.feed.post/1",
        image_index=image_index,
        type=ClueType.ADDRESS_TEXT,
        value=value,
        region=None,
        confidence=0.9,
        source=source,
    )


TOWNS = ["弥生二丁目", "根津一丁目"]


def test_photo_town_needs_both_ocr_and_vlm_to_read_the_same_text() -> None:
    clues = [photo_clue(ClueSource.OCR, "弥生"), photo_clue(ClueSource.VLM, "文京区弥生")]

    found = photo_town_signals(post("近所の猫、今日もいた"), clues, [5, 6], TOWNS)

    assert [(s.kind, s.value, s.clue_indices) for s in found] == [(SignalKind.TOWN, "弥生", (5, 6))]


@pytest.mark.parametrize(
    ("text", "clues"),
    [
        # VLM だけが読んだ
        ("近所の猫", [photo_clue(ClueSource.VLM, "弥生"), photo_clue(ClueSource.VLM, "弥生")]),
        # 別の写真
        ("近所の猫", [photo_clue(ClueSource.OCR, "弥生"), photo_clue(ClueSource.VLM, "弥生", 1)]),
        # 読みが違う
        ("近所の猫", [photo_clue(ClueSource.OCR, "弥生"), photo_clue(ClueSource.VLM, "根津")]),
        # 町名にない文字
        ("近所の猫", [photo_clue(ClueSource.OCR, "銀座"), photo_clue(ClueSource.VLM, "銀座")]),
        # 近所の話ではない
        ("旅行先の猫", [photo_clue(ClueSource.OCR, "弥生"), photo_clue(ClueSource.VLM, "弥生")]),
    ],
)
def test_photo_town_is_not_used_without_agreement_or_relation(text: str, clues: list[Clue]) -> None:
    assert photo_town_signals(post(text), clues, list(range(len(clues))), TOWNS) == []
