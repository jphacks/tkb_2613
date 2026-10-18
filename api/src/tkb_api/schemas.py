"""手がかりの形式。Python 側の正。

web/src/types/clue.ts と同時に変更すること。
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonNegativeInt = Annotated[int, Field(ge=0)]


class ClueType(StrEnum):
    STATION_SIGN = "station_sign"
    ADDRESS_TEXT = "address_text"
    POSTAL_CODE = "postal_code"
    PHONE = "phone"
    SHOP = "shop"
    PLATE = "plate"
    LANDMARK = "landmark"
    EXIF_GPS = "exif_gps"
    FACE = "face"
    IRIS = "iris"
    KEY = "key"
    CODE = "code"


class ClueSource(StrEnum):
    OCR = "ocr"
    VLM = "vlm"
    BROWSER = "browser"


class Clue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ClueType
    value: str
    # 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル）
    region: tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt]
    confidence: float = Field(ge=0.0, le=1.0)
    source: ClueSource

    @model_validator(mode="after")
    def _check_region_order(self) -> Self:
        x1, y1, x2, y2 = self.region
        if x2 <= x1 or y2 <= y1:
            raise ValueError("region は [左上x, 左上y, 右下x, 右下y] で、右下が左上より大きいこと")
        return self


class DetectResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clues: list[Clue]
