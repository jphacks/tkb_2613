import pytest

from tkb_common.bcbp import PNR_MASK, mask_code_value, parse_code_value

# 架空の人物・予約番号。1区間目に任意項目（航空券番号など 0x1C = 28 文字）を付けた形
CONDITIONAL = ">5180  W0305BNH 2A20512345678901"[:28]
ONE_LEG = (
    "M1KAKURE/HARUKI       EQZ7X9K HNDHIJNH 0681 305Y023A0012 11C" + CONDITIONAL + "^160ABCDEF"
)
TWO_LEGS = (
    "M2KAKURE/HARUKI MR    EQZ7X9K HNDHIJNH 0681 305Y023A0012 100"
    "QZ7X9K HIJHNDNH 0686 309Y011C0034 100"
)


def test_parse_reads_name_route_and_day() -> None:
    bp = parse_code_value("PDF417: " + ONE_LEG)

    assert bp is not None
    assert (bp.family_name, bp.given_name) == ("KAKURE", "HARUKI")
    leg = bp.legs[0]
    assert (leg.origin, leg.destination, leg.carrier, leg.flight) == ("HND", "HIJ", "NH", "0681")
    assert leg.julian_day == 305
    assert leg.has_pnr


def test_parse_reads_every_leg_and_drops_title() -> None:
    bp = parse_code_value("AZTEC: " + TWO_LEGS)

    assert bp is not None
    assert bp.given_name == "HARUKI"
    assert [(leg.origin, leg.destination, leg.julian_day) for leg in bp.legs] == [
        ("HND", "HIJ", 305),
        ("HIJ", "HND", 309),
    ]


@pytest.mark.parametrize("prefix", ["PDF417", "AZTEC", "Aztec", "QR_CODE", "QRCode", "DataMatrix"])
def test_parse_accepts_formats_that_carry_bcbp(prefix: str) -> None:
    assert parse_code_value(f"{prefix}: {ONE_LEG}") is not None


@pytest.mark.parametrize(
    "value",
    [
        "Codabar: " + ONE_LEG,  # 搭乗券に使わない種類
        "QRCode: https://example.com/demo",
        "PDF417: " + ONE_LEG[:50],  # 短すぎる
        "PDF417: X" + ONE_LEG[1:],  # 形式コードが M でない
        "PDF417: M1KAKURE HARUKI        E" + ONE_LEG[23:],  # 氏名に「/」がない
        "PDF417: " + ONE_LEG.replace("HNDHIJ", "HN1HIJ"),  # 空港コードが英字3文字でない
        "PDF417: " + ONE_LEG.replace(" 305Y", " 400Y"),  # 通算日が 366 を超える
        "カスタマバーコード: 〒113-0032 住所表示番号 2-99",
    ],
)
def test_parse_ignores_values_that_do_not_fit(value: str) -> None:
    assert parse_code_value(value) is None


def test_mask_hides_pnr_and_drops_optional_items() -> None:
    masked = mask_code_value("PDF417: " + ONE_LEG)

    assert "QZ7X9K" not in masked
    assert "W0305" not in masked and "ABCDEF" not in masked
    assert masked == "PDF417: M1KAKURE/HARUKI       E" + PNR_MASK + "HNDHIJNH 0681 305Y023A0012 100"
    # 伏せたあとも同じように読め、予約番号が読めたことは残る
    bp = parse_code_value(masked)
    assert bp is not None and bp.legs[0].has_pnr


def test_mask_hides_pnr_in_every_leg() -> None:
    masked = mask_code_value("AZTEC: " + TWO_LEGS)

    assert "QZ7X9K" not in masked
    bp = parse_code_value(masked)
    assert bp is not None and len(bp.legs) == 2


@pytest.mark.parametrize(
    "body",
    [
        ONE_LEG.replace("KAKURE/", "ST.JOHN/"),  # 氏名に「.」
        "M2" + ONE_LEG[2:],  # 区間数が実際とずれる
        ONE_LEG[:45],  # 途中で切れた
    ],
)
def test_mask_drops_everything_after_the_pnr_when_the_pass_does_not_fit(body: str) -> None:
    masked = mask_code_value("PDF417: " + body)

    assert "QZ7X9K" not in masked and "W0305" not in masked
    assert masked == "PDF417: " + body[:23] + PNR_MASK
    assert parse_code_value(masked) is None


def test_mask_keeps_other_codes_as_they_are() -> None:
    for value in ["QRCode: https://example.com/demo", "PDF417: not a boarding pass"]:
        assert mask_code_value(value) == value
