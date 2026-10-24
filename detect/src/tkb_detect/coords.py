"""VLM が返した座標を、元の画像のピクセル座標 [左上x, 左上y, 右下x, 右下y] に直す。

qwen3.6-27b（vLLM）は、画像の大きさによらず 0〜1000 の相対値で返す。
2026-10-24 に合成画像で確かめた（縮めずに送った 1600×900 と、1280×720 に縮めて送った
2560×1440 のどちらも 0〜1000 の相対値。json_schema の有無でも同じ）。
モデルを替えたら確かめ直し、COORDINATE_SPACE を見直すこと。None にすると座標が来たら止まる。
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


COORDINATE_SPACE: CoordinateSpace | None = CoordinateSpace.RELATIVE_1000


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
