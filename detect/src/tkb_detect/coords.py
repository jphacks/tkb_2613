"""VLM が返した座標を、元の画像のピクセル座標 [左上x, 左上y, 右下x, 右下y] に直す。

Qwen の座標が 0〜1000 の相対値か、送った画像のピクセルかは、合成画像で確かめてから
COORDINATE_SPACE を決める。決まるまでは None にしておき、座標が来たら止める。
"""

from enum import StrEnum

from tkb_common.schemas import Region
from tkb_detect.image import Size

RELATIVE_SCALE = 1000


class CoordinateSpace(StrEnum):
    # 0〜1000 の相対値
    RELATIVE_1000 = "relative_1000"
    # VLM に送った（縮めた）画像のピクセル
    SENT_PIXELS = "sent_pixels"


# TODO: 合成画像での確認の結果で決める
COORDINATE_SPACE: CoordinateSpace | None = None


def to_original_region(
    box: list[float], space: CoordinateSpace, sent: Size, original: Size
) -> Region | None:
    """元の画像のピクセル座標に直す。画像の外は切り詰め、面積がなくなれば None。"""
    if len(box) != 4:
        return None

    if space is CoordinateSpace.RELATIVE_1000:
        sx, sy = original.width / RELATIVE_SCALE, original.height / RELATIVE_SCALE
    else:
        sx, sy = original.width / sent.width, original.height / sent.height

    x1, y1, x2, y2 = box
    left, right = sorted((round(x1 * sx), round(x2 * sx)))
    top, bottom = sorted((round(y1 * sy), round(y2 * sy)))
    left, right = max(0, left), min(original.width, right)
    top, bottom = max(0, top), min(original.height, bottom)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)
