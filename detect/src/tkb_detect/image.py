"""VLM に送る前の画像の準備。

長い辺を MAX_LONG_SIDE に縮め、JPEG に書き出し直す（EXIF などのメタデータは付けない）。
画像はメモリ上だけで扱い、ディスクには書かない。
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from tkb_detect.errors import DetectError

MAX_LONG_SIDE = 1280
JPEG_QUALITY = 90
# 解凍爆弾を避けるための上限（Bluesky の写真はこれより十分小さい）
MAX_PIXELS = 50_000_000


@dataclass(frozen=True)
class Size:
    width: int
    height: int


@dataclass(frozen=True)
class PreparedImage:
    jpeg: bytes
    # 元の画像（向きを直したあと）の大きさ。手がかりの region はこの座標で返す
    original: Size
    # VLM に送った画像の大きさ
    sent: Size


def _open_rgb(data: bytes) -> Image.Image:
    """画像を開き、EXIF の向きを直した RGB にする。"""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise DetectError("画像が大きすぎます")
            return ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
        raise DetectError(f"画像を読めませんでした: {type(e).__name__}") from e


def prepare_image(data: bytes) -> PreparedImage:
    image = _open_rgb(data)

    original = Size(image.width, image.height)
    image.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=JPEG_QUALITY)
    return PreparedImage(
        jpeg=buf.getvalue(), original=original, sent=Size(image.width, image.height)
    )


# 拡大して読み直すときの切り出し
ZOOM_MIN_LONG_SIDE = 768
ZOOM_MAX_SCALE = 8.0
ZOOM_MARGIN_RATIO = 0.5
ZOOM_MIN_MARGIN_PX = 16


def crop_and_enlarge(data: bytes, region: tuple[int, int, int, int]) -> bytes:
    """元の画像から region のまわりを切り出し、長い辺が ZOOM_MIN_LONG_SIDE 以上になるよう拡大する。

    region は元の画像（向きを直したあと）のピクセル座標。拡大した JPEG を返す。
    """
    image = _open_rgb(data)

    x1, y1, x2, y2 = region
    margin = max(round(max(x2 - x1, y2 - y1) * ZOOM_MARGIN_RATIO), ZOOM_MIN_MARGIN_PX)
    box = (
        max(0, x1 - margin),
        max(0, y1 - margin),
        min(image.width, x2 + margin),
        min(image.height, y2 + margin),
    )
    crop = image.crop(box)

    long_side = max(crop.width, crop.height)
    scale = min(max(ZOOM_MIN_LONG_SIDE / long_side, 1.0), ZOOM_MAX_SCALE)
    if long_side * scale > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    crop = crop.resize(size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
