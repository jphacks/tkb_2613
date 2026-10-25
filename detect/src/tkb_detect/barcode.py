"""写真のバーコードを読む。言語モデルは使わず、画像処理だけで読む。

画像を読む言語モデルは写真を縮小して見るので、バーコードの線の太さを測れず、中身を読めない。
そこで次の2つで読む。どちらも結果は code の手がかりにし、value に中身を書く。

- zxing-cpp：QRコード・宅配伝票（NW-7 など）・JAN など、ふつうのバーコード。
  宅配伝票のバーコードの中身は追跡番号だけで、住所は入っていない
- カスタマバーコード（日本郵便）：郵便物の宛名の近くにある、高さの違う4種類の棒が並んだもの。
  郵便番号7桁と住所表示番号（番地・号・部屋番号など）が入っている。zxing-cpp は読めないので、
  ここで棒の形を測って読む

読んだ中身はメモリ上だけで扱い、ログに出さない。
"""

import io
from dataclasses import dataclass

import numpy as np
import zxingcpp
from numpy.typing import NDArray
from PIL import Image, ImageOps
from scipy import ndimage

from tkb_common.schemas import Clue, ClueSource, ClueType, Region

# 読めたバーコードの確からしさ。zxing-cpp もカスタマバーコードも検査の数字で確かめている
DECODED_CONFIDENCE = 0.98

# ---- カスタマバーコード ----
# 棒の種類：0 ロングバー、1 セミロングバー（上）、2 セミロングバー（下）、3 タイミングバー
FULL, ASC, DESC, TRACK = 0, 1, 2, 3
# 1文字は棒3本。並びは CHARSET の順（日本郵便「バーコードマニュアル」、zint の JapanTable と同じ）
CHARSET = "1234567890-abcdefgh"
PATTERNS: dict[tuple[int, int, int], str] = {
    p: ch
    for ch, p in zip(
        CHARSET,
        [
            (0, 0, 3), (0, 2, 1), (2, 0, 1), (0, 1, 2), (0, 3, 0),
            (2, 1, 0), (1, 0, 2), (1, 2, 0), (3, 0, 0), (0, 3, 3),
            (3, 0, 3), (2, 1, 3), (2, 3, 1), (1, 2, 3), (3, 2, 1),
            (1, 3, 2), (3, 1, 2), (3, 3, 0), (0, 0, 0),
        ],
        strict=True,
    )
}  # fmt: skip
# 検査の数字の値の順
CHECK_ORDER = "0123456789-abcdefgh"
START, STOP = (FULL, DESC), (DESC, FULL)
# スタート2本＋郵便番号7文字＋住所表示番号13文字＋検査1文字（各3本）＋ストップ2本
BAR_COUNT = 2 + (7 + 13 + 1) * 3 + 2
# 棒らしい形：縦が横の何倍以上か、塗りつぶしの割合、いちばん短い棒の高さ（ピクセル）
MIN_ASPECT = 1.5
MIN_FILL = 0.55
MIN_BAR_HEIGHT_PX = 4


@dataclass(frozen=True)
class _Bar:
    x: float
    top: float
    bottom: float
    width: float
    box: tuple[int, int, int, int]  # 左上x, 左上y, 右下x, 右下y


def read_codes(data: bytes, post_id: str, image_index: int) -> list[Clue]:
    """写真のバイト列から、読めたバーコードを code の手がかりにする。読めなければ空。"""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("L")
    clues = [_zxing_clue(r, post_id, image_index, image.size) for r in _zxing(image)]
    for value, box in read_customer_barcodes(image):
        clues.append(_clue(post_id, image_index, value, box, image.size))
    return [c for c in clues if c is not None]


def _zxing(image: Image.Image) -> list[zxingcpp.Barcode]:
    try:
        return [r for r in zxingcpp.read_barcodes(image) if r.valid and r.text]
    except (ValueError, RuntimeError):
        return []


def _zxing_clue(
    result: zxingcpp.Barcode, post_id: str, image_index: int, size: tuple[int, int]
) -> Clue | None:
    p = result.position
    xs = [p.top_left.x, p.top_right.x, p.bottom_left.x, p.bottom_right.x]
    ys = [p.top_left.y, p.top_right.y, p.bottom_left.y, p.bottom_right.y]
    box = (min(xs), min(ys), max(xs), max(ys))
    value = f"{result.format.name}: {result.text}"
    return _clue(post_id, image_index, value, box, size)


def _clue(
    post_id: str,
    image_index: int,
    value: str,
    box: tuple[int, int, int, int],
    size: tuple[int, int],
) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=image_index,
        type=ClueType.CODE,
        value=value,
        region=_region(box, size),
        confidence=DECODED_CONFIDENCE,
        # 言語モデルではなく画像から機械で読んだので、OCR と同じ扱いにする
        source=ClueSource.OCR,
    )


def _region(box: tuple[int, int, int, int], size: tuple[int, int]) -> Region | None:
    w, h = size
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    x2, y2 = min(w, int(box[2]) + 1), min(h, int(box[3]) + 1)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


# ---- カスタマバーコード ----


# 傾いた写真は、まっすぐに直してから読む。0 度で読めなければ、この順に回してみる
DESKEW_ANGLES = (0, 3, -3, 6, -6, 9, -9, 12, -12, 15, -15)
# 読めなかったとき2倍に拡大して読み直すのは、長い辺がこれ以下の画像だけ
# （Bluesky の写真は2000px まで）
UPSCALE_MAX_SIDE_PX = 2000


def read_customer_barcodes(image: Image.Image) -> list[tuple[str, tuple[int, int, int, int]]]:
    """カスタマバーコードを探して読む。(value, 元の画像での枠) の一覧。

    傾いていれば回して直す（少しの傾きは棒の上端・下端の線ごと当てはめる）。上下が逆さでも読む。
    """
    found = _read_any_angle(image)
    if found or max(image.size) > UPSCALE_MAX_SIDE_PX:
        return found
    # 小さく写ったバーコード（棒の幅が2ピクセルほど）は、2倍に拡大して読み直す
    big = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    return [
        (v, (box[0] // 2, box[1] // 2, box[2] // 2, box[3] // 2)) for v, box in _read_any_angle(big)
    ]


def _read_any_angle(image: Image.Image) -> list[tuple[str, tuple[int, int, int, int]]]:
    for angle in DESKEW_ANGLES:
        rotated = image.rotate(angle, expand=True, fillcolor=255) if angle else image
        found = _read_upright(rotated)
        if found:
            return [(v, _unrotate(box, angle, image.size, rotated.size)) for v, box in found]
    return []


def _unrotate(
    box: tuple[int, int, int, int], angle: float, size: tuple[int, int], rotated: tuple[int, int]
) -> tuple[int, int, int, int]:
    """回した画像の枠を、元の画像の枠に戻す（4隅を戻して、囲む枠にする）。"""
    if not angle:
        return box
    t = np.radians(angle)
    cx, cy = size[0] / 2, size[1] / 2
    rx, ry = rotated[0] / 2, rotated[1] / 2
    xs, ys = [], []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])):
        dx, dy = x - rx, y - ry
        xs.append(cx + dx * np.cos(t) - dy * np.sin(t))
        ys.append(cy + dx * np.sin(t) + dy * np.cos(t))
    return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


def _read_upright(image: Image.Image) -> list[tuple[str, tuple[int, int, int, int]]]:
    gray = np.asarray(image, dtype=np.uint8)
    dark = gray < _otsu(gray)
    bars = _bars(dark)
    found = []
    for row in _rows(bars):
        for start in range(len(row) - BAR_COUNT + 1):
            window = row[start : start + BAR_COUNT]
            kinds = _classify(window)
            if kinds is None:
                continue
            decoded = decode_customer_barcode(kinds)
            if decoded is None:
                continue
            box = (
                min(b.box[0] for b in window),
                min(b.box[1] for b in window),
                max(b.box[2] for b in window),
                max(b.box[3] for b in window),
            )
            found.append((decoded, box))
            break
    return found


def decode_customer_barcode(kinds: list[int]) -> str | None:
    """棒の種類の並び（67本）を読む。検査の数字が合わなければ None。逆さの並びも読む。"""
    for seq in (kinds, [{ASC: DESC, DESC: ASC}.get(k, k) for k in reversed(kinds)]):
        text = _decode_forward(seq)
        if text is not None:
            return text
    return None


def _decode_forward(kinds: list[int]) -> str | None:
    if len(kinds) != BAR_COUNT or tuple(kinds[:2]) != START or tuple(kinds[-2:]) != STOP:
        return None
    chars = []
    for i in range(2, BAR_COUNT - 2, 3):
        ch = PATTERNS.get((kinds[i], kinds[i + 1], kinds[i + 2]))
        if ch is None:
            return None
        chars.append(ch)
    data, check = chars[:-1], chars[-1]
    total = sum(CHECK_ORDER.index(ch) for ch in data)
    if CHECK_ORDER[(19 - total % 19) % 19] != check:
        return None
    postal = "".join(data[:7])
    if not postal.isdigit():
        return None
    address = _address(data[7:])
    if address is None:
        return None
    text = f"カスタマバーコード: 〒{postal[:3]}-{postal[3:]}"
    return text + (f" 住所表示番号 {address}" if address else "")


def _address(chars: list[str]) -> str | None:
    """住所表示番号の13文字。a〜c と数字の組は英字、d は埋め草。"""
    out = []
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch.isdigit() or ch == "-":
            out.append(ch)
        elif ch in "abc" and i + 1 < len(chars) and chars[i + 1].isdigit():
            offset = "abc".index(ch) * 10 + int(chars[i + 1])
            if offset >= 26:
                return None
            out.append(chr(ord("A") + offset))
            i += 1
        elif ch == "d":
            pass
        else:
            return None
        i += 1
    return "".join(out).strip("-")


def _otsu(gray: NDArray[np.uint8]) -> float:
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = hist.sum()
    levels = np.arange(256)
    weight = np.cumsum(hist)
    mean = np.cumsum(hist * levels)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean[-1] * weight / total - mean) ** 2 / (weight * (total - weight))
    if np.isnan(between).all():
        # 一色だけの画像
        return 0.0
    return float(np.nanargmax(between))


def _bars(dark: NDArray[np.bool_]) -> list[_Bar]:
    labels, _ = ndimage.label(dark)
    areas = np.bincount(labels.ravel())
    bars = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if h < MIN_BAR_HEIGHT_PX or h < MIN_ASPECT * w:
            continue
        if areas[i] < MIN_FILL * h * w:
            continue
        bars.append(
            _Bar(
                x=(sl[1].start + sl[1].stop - 1) / 2,
                top=float(sl[0].start),
                bottom=float(sl[0].stop - 1),
                width=float(w),
                box=(sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1),
            )
        )
    return bars


def _rows(bars: list[_Bar]) -> list[list[_Bar]]:
    """左から並んだ棒の列。同じくらいの太さで、間隔がそろい、隣どうしが中央の帯を共有する
    ものを1列にする。"""
    rows: list[list[_Bar]] = []
    used: set[int] = set()
    ordered = sorted(range(len(bars)), key=lambda i: bars[i].x)
    for n, first in enumerate(ordered):
        if first in used:
            continue
        row = [bars[first]]
        members = [first]
        for j in ordered[n + 1 :]:
            if j in used or bars[j].x <= row[-1].x:
                continue
            b, last = bars[j], row[-1]
            gap = b.x - last.x
            pitch = (row[-1].x - row[0].x) / (len(row) - 1) if len(row) > 1 else 3 * last.width
            if gap > 1.8 * pitch:
                if gap > 4 * pitch:
                    break
                continue
            if gap < 0.5 * pitch or not 0.5 * last.width <= b.width <= 2 * last.width:
                continue
            # 隣の棒と中央の帯（タイミングバーの高さ）を共有していること。写真の傾きで帯が
            # 少しずつずれるので、列全体ではなく隣どうしで比べる
            overlap = min(last.bottom, b.bottom) - max(last.top, b.top)
            if overlap < 0.3 * min(last.bottom - last.top, b.bottom - b.top):
                continue
            row.append(b)
            members.append(j)
        if len(row) >= BAR_COUNT:
            rows.append(row)
            used.update(members)
    return rows


def _classify(window: list[_Bar]) -> list[int] | None:
    """棒の上端・下端が、上の線と中の線のどちらに近いかで種類を決める。傾きは直線で吸収する。"""
    x = np.array([b.x for b in window])
    tops = np.array([b.top for b in window])
    bottoms = np.array([b.bottom for b in window])
    high = _two_lines(x, tops)
    low = _two_lines(x, bottoms)
    if high is None or low is None:
        return None
    up = high[0]  # 上に伸びている（ロングバー・セミロングバー上）
    down = low[1]  # 下に伸びている
    kinds = []
    for u, d in zip(up, down, strict=True):
        kinds.append(
            {(True, True): FULL, (True, False): ASC, (False, True): DESC}.get((u, d), TRACK)
        )
    return kinds


def _two_lines(
    x: NDArray[np.float64], y: NDArray[np.float64]
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]] | None:
    """y を2本の直線に分ける。(小さい側か, 大きい側か) の真偽の配列。線の差が小さすぎれば None。"""
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    small = resid < 0
    for _ in range(10):
        if small.all() or not small.any():
            return None
        a = np.polyfit(x[small], y[small], 1) if small.sum() >= 2 else (0.0, y[small].mean())
        b = np.polyfit(x[~small], y[~small], 1) if (~small).sum() >= 2 else (0.0, y[~small].mean())
        da = np.abs(y - (a[0] * x + a[1]))
        db = np.abs(y - (b[0] * x + b[1]))
        new = da < db
        if (new == small).all():
            break
        small = new
    gap = np.abs((b[0] * x + b[1]) - (a[0] * x + a[1])).mean()
    spread = max(float(np.abs(y - np.where(small, a[0] * x + a[1], b[0] * x + b[1])).max()), 1.0)
    if gap < 2 * spread:
        return None
    return small, ~small
