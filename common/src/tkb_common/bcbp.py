"""搭乗券のバーコード（IATA の BCBP、Resolution 792 の M 形式）を読む。

写真の code の手がかり（zxing が読んだ「PDF417: M1…」「AZTEC: M1…」「QR_CODE: M1…」）の
中身を、決まった桁の区切りで読む。形式に合わないものは None にする。

予約番号（PNR）は、読めたかどうかだけを残し、中身は使わない。detect は手がかりを作る時点で
mask_code_value で予約番号を「*」に置き換え、任意項目（航空券番号・会員番号など）と
セキュリティデータを落とす。手がかりの値は API の応答に載るので、そこにも予約番号を出さない。

必須項目の桁（1区間目は 60 文字）：
  形式コード M(1) 区間数(1) 氏名(20) 電子航空券の印(1)
  区間ごとに：予約番号(7) 出発地(3) 到着地(3) 航空会社(3) 便名(5) 搭乗日(3、年の通算日)
             座席の等級(1) 座席番号(4) 搭乗の順番(5) 乗客の状態(1) 任意項目の長さ(2、16進)
"""

import re
from dataclasses import dataclass

# BCBP を載せるバーコードの種類。zxing の名前（PDF417 / Aztec / QRCode / DataMatrix）と、
# ほかの書き方（AZTEC / QR_CODE）の両方を受け付ける。比べるときは大文字にして「_」を落とす
BCBP_FORMATS = frozenset({"PDF417", "AZTEC", "QRCODE", "DATAMATRIX"})
MAX_LEGS = 4
HEADER_LEN = 23  # 形式コード・区間数・氏名・電子航空券の印
LEG_LEN = 37  # 区間ごとの必須項目（任意項目の長さまで）
PNR_LEN = 7
PNR_MASK = "*" * PNR_LEN

AIRPORT = re.compile(r"[A-Z]{3}")
NAME = re.compile(r"[A-Z][A-Z '\-]*/[A-Z '\-]*")
# 氏名の後ろに付くことがある敬称（空白で区切られたものだけ落とす）
TITLES = re.compile(r"\s+(?:MR|MS|MRS|MSTR|MISS|DR)$")


@dataclass(frozen=True)
class BoardingLeg:
    """搭乗券の1区間。予約番号は中身を持たず、読めたかどうか（has_pnr）だけ。"""

    origin: str
    destination: str
    carrier: str
    flight: str
    julian_day: int
    has_pnr: bool


@dataclass(frozen=True)
class BoardingPass:
    family_name: str
    given_name: str
    legs: tuple[BoardingLeg, ...]


def split_code_value(value: str) -> tuple[str, str] | None:
    """「PDF417: M1…」を (バーコードの種類, 中身) に分ける。BCBP を載せない種類なら None。"""
    head, sep, body = value.partition(": ")
    if not sep or head.upper().replace("_", "") not in BCBP_FORMATS:
        return None
    return head, body


def parse_code_value(value: str) -> BoardingPass | None:
    """code の手がかりの値を搭乗券として読む。形式に合わなければ None。"""
    split = split_code_value(value)
    if split is None:
        return None
    parsed = _parse(split[1])
    return parsed[0] if parsed else None


def mask_code_value(value: str) -> str:
    """搭乗券なら予約番号を伏せ、必須項目だけを残した値にする。搭乗券でなければそのまま。"""
    split = split_code_value(value)
    if split is None:
        return value
    head, body = split
    parsed = _parse(body)
    if parsed is None:
        # 「M」と数字で始まるのに形式に合わない（切れた・ずれた）なら搭乗券かもしれない。
        # 予約番号の位置から後ろをすべて落とし、そのまま返さない
        if len(body) > HEADER_LEN and body[0] == "M" and body[1].isdigit():
            return f"{head}: {body[:HEADER_LEN]}{PNR_MASK}"
        return value
    _, segments = parsed
    legs = "".join(
        (PNR_MASK if segment[:PNR_LEN].strip() else " " * PNR_LEN) + segment[PNR_LEN:-2] + "00"
        for segment in segments
    )
    return f"{head}: {body[:HEADER_LEN]}{legs}"


def _parse(body: str) -> tuple[BoardingPass, list[str]] | None:
    """(読んだ搭乗券, 区間ごとの必須項目の文字列) を返す。"""
    if len(body) < HEADER_LEN + LEG_LEN or body[0] != "M" or not body[1].isdigit():
        return None
    count = int(body[1])
    if not 1 <= count <= MAX_LEGS:
        return None
    name = _name(body[2:22])
    if name is None:
        return None
    legs: list[BoardingLeg] = []
    segments: list[str] = []
    pos = HEADER_LEN
    for _ in range(count):
        segment = body[pos : pos + LEG_LEN]
        leg = _leg(segment)
        if leg is None:
            return None
        legs.append(leg)
        segments.append(segment)
        pos += LEG_LEN + int(segment[-2:], 16)
    return BoardingPass(name[0], name[1], tuple(legs)), segments


def _name(field: str) -> tuple[str, str] | None:
    text = TITLES.sub("", field.strip())
    if not NAME.fullmatch(text):
        return None
    family, given = (part.strip() for part in text.split("/", 1))
    return (family, given) if family else None


def _leg(segment: str) -> BoardingLeg | None:
    if len(segment) != LEG_LEN:
        return None
    origin, destination = segment[7:10], segment[10:13]
    day = segment[21:24]
    size = segment[35:37]
    if (
        not AIRPORT.fullmatch(origin)
        or not AIRPORT.fullmatch(destination)
        or not day.isdigit()
        or not 1 <= int(day) <= 366
        or not re.fullmatch(r"[0-9A-Fa-f]{2}", size)
    ):
        return None
    return BoardingLeg(
        origin=origin,
        destination=destination,
        carrier=segment[13:16].strip(),
        flight=segment[16:21].strip(),
        julian_day=int(day),
        has_pnr=bool(segment[:PNR_LEN].strip()),
    )
