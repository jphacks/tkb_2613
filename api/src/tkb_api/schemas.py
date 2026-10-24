"""api の入出力の形式。Python 側の正。

手がかりは web/src/types/clue.ts、ログインは web/src/types/session.ts と同時に変更すること。
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

NonNegativeInt = Annotated[int, Field(ge=0)]
Region = tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt]


class ClueType(StrEnum):
    # 写真から
    STATION_SIGN = "station_sign"
    RAIL_VIEW = "rail_view"
    REFLECTION = "reflection"
    SHOP = "shop"
    LANDMARK = "landmark"
    ADDRESS_TEXT = "address_text"
    POSTAL_CODE = "postal_code"
    PHONE = "phone"
    PLATE = "plate"
    UNIFORM = "uniform"
    FACE = "face"
    KEY = "key"
    CODE = "code"
    # 写真と本文の両方から
    NAME_TEXT = "name_text"
    ORG_TEXT = "org_text"
    HANDLE_TEXT = "handle_text"
    PLACE_TEXT = "place_text"
    # 本文から
    AGE_TEXT = "age_text"
    ROUTINE_TEXT = "routine_text"
    RELATION_TEXT = "relation_text"


PHOTO_ONLY_TYPES = frozenset(
    {
        ClueType.STATION_SIGN,
        ClueType.RAIL_VIEW,
        ClueType.REFLECTION,
        ClueType.SHOP,
        ClueType.LANDMARK,
        ClueType.ADDRESS_TEXT,
        ClueType.POSTAL_CODE,
        ClueType.PHONE,
        ClueType.PLATE,
        ClueType.UNIFORM,
        ClueType.FACE,
        ClueType.KEY,
        ClueType.CODE,
    }
)
TEXT_ONLY_TYPES = frozenset({ClueType.AGE_TEXT, ClueType.ROUTINE_TEXT, ClueType.RELATION_TEXT})


class ClueSource(StrEnum):
    OCR = "ocr"
    VLM = "vlm"
    TEXT = "text"  # 本文から
    META = "meta"  # 投稿時刻などから


PHOTO_SOURCES = frozenset({ClueSource.OCR, ClueSource.VLM})


class Clue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str = Field(min_length=1)
    # 写真から出た手がかりだけに入れる。本文から出たものは None
    image_index: NonNegativeInt | None
    type: ClueType
    # 一部しか読めない文字は、読めない桁や文字を x にする（例：270-01xx）
    value: str
    # 画像上の矩形 [左上x, 左上y, 右下x, 右下y]（ピクセル）。写真の手がかりでも位置がなければ None
    region: Region | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: ClueSource

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        from_photo = self.image_index is not None
        if self.region is not None:
            if not from_photo:
                raise ValueError("region は写真の手がかり（image_index がある）だけに入れること")
            x1, y1, x2, y2 = self.region
            if x2 <= x1 or y2 <= y1:
                raise ValueError(
                    "region は [左上x, 左上y, 右下x, 右下y] で、右下が左上より大きいこと"
                )
        if from_photo != (self.source in PHOTO_SOURCES):
            raise ValueError("source が ocr / vlm のときだけ image_index を入れること")
        if self.type in PHOTO_ONLY_TYPES and not from_photo:
            raise ValueError(f"{self.type} は写真の手がかりなので image_index が要る")
        if self.type in TEXT_ONLY_TYPES and from_photo:
            raise ValueError(f"{self.type} は本文の手がかりなので image_index は入れない")
        return self


class DetectResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clues: list[Clue]


class SessionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str = Field(min_length=1, max_length=253)
    # アカウントのパスワードかアプリパスワード。ログインに使うだけで保存しない。
    # SecretStr にして、repr やエラーの文言にパスワードが出ないようにする
    password: SecretStr

    @field_validator("handle")
    @classmethod
    def _normalize_handle(cls, value: str) -> str:
        handle = value.strip().removeprefix("@")
        if not handle:
            raise ValueError("ハンドル名を入れてください")
        return handle

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("パスワードを入れてください")
        return value


class SessionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    handle: str
    did: str
