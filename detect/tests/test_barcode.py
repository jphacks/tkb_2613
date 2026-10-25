import io

import pytest
import zxingcpp
from PIL import Image, ImageDraw

from tkb_common.schemas import ClueSource, ClueType
from tkb_detect.barcode import (
    ASC,
    CHARSET,
    CHECK_ORDER,
    DESC,
    FULL,
    PATTERNS,
    START,
    STOP,
    TRACK,
    decode_customer_barcode,
    read_codes,
)

CODE_OF = {ch: p for p, ch in PATTERNS.items()}


def _encode(postal: str, address: str) -> list[int]:
    """テスト用：カスタマバーコードの棒の並び（英字は使わない）。"""
    chars = list(postal) + list(address)
    chars += ["d"] * (20 - len(chars))
    total = sum(CHECK_ORDER.index(ch) for ch in chars)
    chars.append(CHECK_ORDER[(19 - total % 19) % 19])
    kinds = list(START)
    for ch in chars:
        kinds.extend(CODE_OF[ch])
    return kinds + list(STOP)


def _draw(kinds: list[int], angle: float = 0.0, scale: int = 3) -> bytes:
    """封筒の宛名の一部のような画像に描く。"""
    img = Image.new("L", (520 * scale // 3, 220 * scale // 3), 250)
    d = ImageDraw.Draw(img)
    d.text((20, 15), "〒xxx-xxxx tokyo hachioji", fill=30)
    x0, mid = 30, 120 * scale // 3
    unit = 4 * scale // 3  # タイミングバーの半分の高さ
    for n, k in enumerate(kinds):
        x = x0 + n * 2 * scale
        top = mid - (3 * unit if k in (FULL, ASC) else unit)
        bottom = mid + (3 * unit if k in (FULL, DESC) else unit)
        d.rectangle([x, top, x + scale - 1, bottom], fill=10)
    img = img.rotate(angle, expand=True, fillcolor=250)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def test_patterns_cover_every_character() -> None:
    assert sorted(PATTERNS.values()) == sorted(CHARSET)


def test_decode_reads_postal_code_and_address_number() -> None:
    kinds = _encode("1920083", "9-3")
    assert decode_customer_barcode(kinds) == "カスタマバーコード: 〒192-0083 住所表示番号 9-3"


def test_decode_reads_letters_and_upside_down() -> None:
    # 「3-2-1-A」の A は CC1 と 0
    chars = list("1000001") + list("3-2-1-") + ["a", "0"]
    chars += ["d"] * (20 - len(chars))
    total = sum(CHECK_ORDER.index(ch) for ch in chars)
    chars.append(CHECK_ORDER[(19 - total % 19) % 19])
    kinds = list(START) + [k for ch in chars for k in CODE_OF[ch]] + list(STOP)
    upside_down = [{ASC: DESC, DESC: ASC}.get(k, k) for k in reversed(kinds)]

    assert decode_customer_barcode(upside_down) == (
        "カスタマバーコード: 〒100-0001 住所表示番号 3-2-1-A"
    )


def test_decode_rejects_a_wrong_check_digit() -> None:
    kinds = _encode("1920083", "9-3")
    kinds[-5] = TRACK if kinds[-5] != TRACK else FULL
    assert decode_customer_barcode(kinds) is None


@pytest.mark.parametrize(("angle", "scale"), [(0, 2), (2, 3), (-5, 3), (8, 4), (-11, 3)])
def test_read_codes_finds_a_customer_barcode_in_a_tilted_photo(angle: float, scale: int) -> None:
    data = _draw(_encode("1920083", "9-3"), angle=angle, scale=scale)

    clues = read_codes(data, "p1", 0)

    assert [c.value for c in clues] == ["カスタマバーコード: 〒192-0083 住所表示番号 9-3"]
    clue = clues[0]
    assert clue.type is ClueType.CODE
    assert clue.source is ClueSource.OCR
    # 枠は元の画像の中で、宛名の文字（上のほう）ではなくバーコードのあたり
    assert clue.region is not None
    width, height = Image.open(io.BytesIO(data)).size
    _, y1, x2, y2 = clue.region
    assert x2 <= width and y2 <= height
    assert (y1 + y2) / 2 > height * 0.35


def test_read_codes_reads_qr_and_shipping_label_codes() -> None:
    img = Image.new("L", (900, 400), 255)
    qr = zxingcpp.create_barcode("https://example.com/demo", zxingcpp.BarcodeFormat.QRCode)
    label = zxingcpp.create_barcode("A123456789012A", zxingcpp.BarcodeFormat.Codabar)
    img.paste(Image.fromarray(qr.to_image(scale=6)), (20, 20))
    img.paste(Image.fromarray(label.to_image(scale=2)), (330, 120))
    buf = io.BytesIO()
    img.save(buf, "PNG")

    values = sorted(c.value for c in read_codes(buf.getvalue(), "p1", 0))

    assert values == ["Codabar: A123456789012A", "QRCode: https://example.com/demo"]


def test_read_codes_returns_nothing_for_a_plain_photo() -> None:
    img = Image.new("RGB", (300, 200), (120, 160, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG")

    assert read_codes(buf.getvalue(), "p1", 0) == []
