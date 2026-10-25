"""api・detect・engine で共有する形式（投稿、手がかり、プロフィール）。Python 側の正。

投稿・手がかり・プロフィールの型は web/src/types/ の対応ファイルと同時に変更すること。
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
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
    LOCAL_ITEM = "local_item"
    NOTICE = "notice"
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
        ClueType.LOCAL_ITEM,
        ClueType.NOTICE,
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


class ProfileAttribute(StrEnum):
    """安定したプロフィール項目ID。推定可能性を保証するものではない。"""

    FACIAL_APPEARANCE = "facial_appearance"
    FULL_NAME = "full_name"
    GIVEN_NAME_OR_NICKNAME = "given_name_or_nickname"
    OTHER_SOCIAL_ACCOUNT = "other_social_account"
    REALTIME_LOCATION = "realtime_location"
    HOME_BUILDING_OR_ROOM = "home_building_or_room"
    COMMUTE_STATION_OR_LINE = "commute_station_or_line"
    RESIDENTIAL_AREA = "residential_area"
    LONG_TERM_HOME_ABSENCE = "long_term_home_absence"
    WORKPLACE = "workplace"
    WORKPLACE_AREA = "workplace_area"
    SCHOOL = "school"
    FREQUENT_SHOP = "frequent_shop"
    VEHICLE_MODEL_OR_PARTIAL_PLATE = "vehicle_model_or_partial_plate"
    PARTNER_STATUS_AND_ATTRIBUTES = "partner_status_and_attributes"
    CHILDREN_AGE_AND_SCHOOL = "children_age_and_school"


class ProfileCategory(StrEnum):
    IDENTITY_AND_FACE = "identity_and_face"
    HOME_AND_LOCATION = "home_and_location"
    AFFILIATION_AND_WORK = "affiliation_and_work"
    ACTIVITY_AND_FAMILY = "activity_and_family"


PROFILE_CATEGORY_LABELS: dict[ProfileCategory, str] = {
    ProfileCategory.IDENTITY_AND_FACE: "身元・顔",
    ProfileCategory.HOME_AND_LOCATION: "自宅・位置",
    ProfileCategory.AFFILIATION_AND_WORK: "所属・職場",
    ProfileCategory.ACTIVITY_AND_FAMILY: "行動圏・家族",
}


class PersonalLevel(IntEnum):
    LEVEL_4 = 4
    LEVEL_5 = 5


class Guessability(StrEnum):
    A = "A"
    A_TO_B = "A〜B"
    B = "B"


@dataclass(frozen=True)
class ProfileAttributeMetadata:
    label: str
    category: ProfileCategory
    personal_level: PersonalLevel
    guessability: Guessability


# 静的な表示カタログ。ここにあることは、実際に推定できるという意味ではない。
PROFILE_ATTRIBUTE_CATALOG: dict[ProfileAttribute, ProfileAttributeMetadata] = {
    ProfileAttribute.FACIAL_APPEARANCE: ProfileAttributeMetadata(
        "顔貌（自撮り・他撮り・反射）",
        ProfileCategory.IDENTITY_AND_FACE,
        PersonalLevel.LEVEL_5,
        Guessability.A,
    ),
    ProfileAttribute.FULL_NAME: ProfileAttributeMetadata(
        "本名（フルネーム）",
        ProfileCategory.IDENTITY_AND_FACE,
        PersonalLevel.LEVEL_5,
        Guessability.B,
    ),
    ProfileAttribute.GIVEN_NAME_OR_NICKNAME: ProfileAttributeMetadata(
        "下の名前 / 呼ばれている名前",
        ProfileCategory.IDENTITY_AND_FACE,
        PersonalLevel.LEVEL_4,
        Guessability.A_TO_B,
    ),
    ProfileAttribute.OTHER_SOCIAL_ACCOUNT: ProfileAttributeMetadata(
        "別SNSのアカウント / 本垢",
        ProfileCategory.IDENTITY_AND_FACE,
        PersonalLevel.LEVEL_4,
        Guessability.A,
    ),
    ProfileAttribute.REALTIME_LOCATION: ProfileAttributeMetadata(
        "リアルタイムの現在地",
        ProfileCategory.HOME_AND_LOCATION,
        PersonalLevel.LEVEL_5,
        Guessability.A,
    ),
    ProfileAttribute.HOME_BUILDING_OR_ROOM: ProfileAttributeMetadata(
        "自宅の建物外観・部屋の位置",
        ProfileCategory.HOME_AND_LOCATION,
        PersonalLevel.LEVEL_5,
        Guessability.B,
    ),
    ProfileAttribute.COMMUTE_STATION_OR_LINE: ProfileAttributeMetadata(
        "最寄り駅 / 日常の利用路線",
        ProfileCategory.HOME_AND_LOCATION,
        PersonalLevel.LEVEL_4,
        Guessability.A_TO_B,
    ),
    ProfileAttribute.RESIDENTIAL_AREA: ProfileAttributeMetadata(
        "居住エリア（市区町村・町域）",
        ProfileCategory.HOME_AND_LOCATION,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
    ProfileAttribute.LONG_TERM_HOME_ABSENCE: ProfileAttributeMetadata(
        "自宅の長期不在（旅行・帰省中）",
        ProfileCategory.HOME_AND_LOCATION,
        PersonalLevel.LEVEL_4,
        Guessability.A_TO_B,
    ),
    ProfileAttribute.WORKPLACE: ProfileAttributeMetadata(
        "勤務先（企業名・店舗・ビル）",
        ProfileCategory.AFFILIATION_AND_WORK,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
    ProfileAttribute.WORKPLACE_AREA: ProfileAttributeMetadata(
        "勤務先エリア（オフィス街）",
        ProfileCategory.AFFILIATION_AND_WORK,
        PersonalLevel.LEVEL_4,
        Guessability.A_TO_B,
    ),
    ProfileAttribute.SCHOOL: ProfileAttributeMetadata(
        "通学先（大学・キャンパス・学校）",
        ProfileCategory.AFFILIATION_AND_WORK,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
    ProfileAttribute.FREQUENT_SHOP: ProfileAttributeMetadata(
        "行きつけの店（ジム・美容院・カフェ）",
        ProfileCategory.ACTIVITY_AND_FAMILY,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
    ProfileAttribute.VEHICLE_MODEL_OR_PARTIAL_PLATE: ProfileAttributeMetadata(
        "自家用車の車種・ナンバー（一部）",
        ProfileCategory.ACTIVITY_AND_FAMILY,
        PersonalLevel.LEVEL_4,
        Guessability.A_TO_B,
    ),
    ProfileAttribute.PARTNER_STATUS_AND_ATTRIBUTES: ProfileAttributeMetadata(
        "配偶者・交際相手の有無と属性",
        ProfileCategory.ACTIVITY_AND_FAMILY,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
    ProfileAttribute.CHILDREN_AGE_AND_SCHOOL: ProfileAttributeMetadata(
        "子どもの有無・年齢・通園通学先",
        ProfileCategory.ACTIVITY_AND_FAMILY,
        PersonalLevel.LEVEL_4,
        Guessability.B,
    ),
}


class ProfileStatus(StrEnum):
    FOUND = "found"
    WEAK = "weak"
    UNKNOWN = "unknown"


class ProfileEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str = Field(min_length=1)
    clue_index: NonNegativeInt
    required: bool


class ProfileItem(BaseModel):
    """プロフィール出力の型。confidence は校正済み確率を意味しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: ProfileAttribute
    value: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    status: ProfileStatus
    evidence: list[ProfileEvidence]

    @model_validator(mode="after")
    def _check_value_for_status(self) -> Self:
        if self.status is ProfileStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("unknown の value は null にすること")
        elif self.value is None or not self.value.strip():
            raise ValueError("found / weak の value は空でない文字列にすること")
        return self
