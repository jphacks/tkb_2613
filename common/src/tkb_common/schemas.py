"""api・detect・engine で共有する形式（投稿と手がかり）。Python 側の正。

投稿は web/src/types/post.ts、手がかりは web/src/types/clue.ts と同時に変更すること。
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
Region = tuple[NonNegativeInt, NonNegativeInt, NonNegativeInt, NonNegativeInt]

# 画像を取りに行ってよいのは Bluesky の CDN だけ
BSKY_CDN_PREFIX = "https://cdn.bsky.app/"
# Bluesky の投稿に付けられる写真は4枚まで
MAX_IMAGES_PER_POST = 4


class PostImage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: NonNegativeInt
    url: str
    alt: str
    width: PositiveInt
    height: PositiveInt

    @field_validator("url")
    @classmethod
    def _check_cdn(cls, value: str) -> str:
        if not value.startswith(BSKY_CDN_PREFIX):
            raise ValueError(f"画像の URL は {BSKY_CDN_PREFIX} で始まること")
        return value


class Post(BaseModel):
    """Bluesky から取得した投稿。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str = Field(min_length=1)
    text: str
    created_at: AwareDatetime
    images: list[PostImage] = Field(max_length=MAX_IMAGES_PER_POST)

    @model_validator(mode="after")
    def _check_image_order(self) -> Self:
        if [image.index for image in self.images] != list(range(len(self.images))):
            raise ValueError("images の index は 0 から順に並べること")
        return self


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
