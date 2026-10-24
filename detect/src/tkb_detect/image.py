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


def prepare_image(data: bytes) -> PreparedImage:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise DetectError("画像が大きすぎます")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
        raise DetectError(f"画像を読めませんでした: {type(e).__name__}") from e

    original = Size(image.width, image.height)
    image.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=JPEG_QUALITY)
    return PreparedImage(
        jpeg=buf.getvalue(), original=original, sent=Size(image.width, image.height)
    )
