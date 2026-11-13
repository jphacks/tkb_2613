"""api・detect・engine で共有する形式（投稿、手がかり、プロフィール）。Python 側の正。

投稿・手がかり・プロフィールの型は web/src/types/ の対応ファイルと同時に変更すること。
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

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
    # ローカルモック画像の表示用。実モードの画像取得には使わない。
    mock_asset: str | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("url")
    @classmethod
    def _check_cdn(cls, value: str) -> str:
        if not value.startswith(BSKY_CDN_PREFIX):
            raise ValueError(f"画像の URL は {BSKY_CDN_PREFIX} で始まること")
        return value

    @field_validator("mock_asset")
    @classmethod
    def _check_mock_asset(cls, value: str | None) -> str | None:
        if value is not None and (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value) or value in {".", ".."}
        ):
            raise ValueError("mock_asset は安全なファイル名であること")
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
    VEHICLE_MODEL = "vehicle_model"
    UNIFORM = "uniform"
    FACE = "face"
    KEY = "key"
    CODE = "code"
    NOTICE = "notice"
    # 写真と本文の両方から
    LOCAL_ITEM = "local_item"
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
        ClueType.NOTICE,
    }
)
TEXT_ONLY_TYPES = frozenset({ClueType.AGE_TEXT, ClueType.ROUTINE_TEXT, ClueType.RELATION_TEXT})


class ClueSource(StrEnum):
    OCR = "ocr"
    VLM = "vlm"
    TEXT = "text"  # 本文から
    ALT = "alt"  # 画像に付いた代替テキスト
    PROFILE_TEXT = "profile_text"  # 本人プロフィールの自己申告文
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
    # Ollama 本文抽出時の原文根拠。従来の手がかりでは None。
    quote: str | None = Field(default=None, exclude_if=lambda value: value is None)

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
        if from_photo != (self.source in PHOTO_SOURCES or self.source is ClueSource.ALT):
            raise ValueError("source が ocr / vlm のときだけ image_index を入れること")
        if self.type in PHOTO_ONLY_TYPES and self.source not in PHOTO_SOURCES:
            raise ValueError(f"{self.type} は写真の手がかりなので image_index が要る")
        if self.type in TEXT_ONLY_TYPES and self.source in PHOTO_SOURCES:
            raise ValueError(f"{self.type} は本文の手がかりなので image_index は入れない")
        return self


class DetectResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clues: list[Clue]


class ProfileAttribute(StrEnum):
    """安定したプロフィール項目ID。推定可能性を保証するものではない。"""

    FACIAL_APPEARANCE = "facial_appearance"
    FULL_NAME = "full_name"
    GIVEN_NAME = "given_name"
    NICKNAME = "nickname"
    OTHER_SOCIAL_ACCOUNT = "other_social_account"
    REALTIME_LOCATION = "realtime_location"
    HOME_BUILDING = "home_building"
    HOME_ROOM = "home_room"
    HOME_NEAREST_STATION = "home_nearest_station"
    REGULAR_STATION = "regular_station"
    REGULAR_LINE = "regular_line"
    RESIDENTIAL_AREA = "residential_area"
    ANNOUNCED_LONG_ABSENCE = "announced_long_absence"
    ACTUAL_HOME_ABSENCE = "actual_home_absence"
    EMPLOYER_NAME = "employer_name"
    WORKPLACE_BUILDING_CANDIDATE = "workplace_building_candidate"
    WORKPLACE_AREA = "workplace_area"
    SCHOOL = "school"
    FREQUENT_SHOP = "frequent_shop"
    VEHICLE_MODEL = "vehicle_model"
    PARTIAL_PLATE = "partial_plate"
    PARTNER_STATUS = "partner_status"
    PARTNER_ATTRIBUTES = "partner_attributes"
    CHILD_AGE = "child_age"
    CHILD_SCHOOL = "child_school"


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


@dataclass(frozen=True)
class ProfileAttributeMetadata:
    label: str
    category: ProfileCategory
    personal_level: None = None  # deprecated
    guessability: None = None  # deprecated


# 静的な表示カタログ。ここにあることは、実際に推定できるという意味ではない。
PROFILE_ATTRIBUTE_CATALOG: dict[ProfileAttribute, ProfileAttributeMetadata] = {
    ProfileAttribute.FACIAL_APPEARANCE: ProfileAttributeMetadata(
        "顔貌（自撮り・他撮り・反射）",
        ProfileCategory.IDENTITY_AND_FACE,
    ),
    ProfileAttribute.FULL_NAME: ProfileAttributeMetadata(
        "本名（フルネーム）",
        ProfileCategory.IDENTITY_AND_FACE,
    ),
    ProfileAttribute.GIVEN_NAME: ProfileAttributeMetadata(
        "下の名前", ProfileCategory.IDENTITY_AND_FACE
    ),
    ProfileAttribute.NICKNAME: ProfileAttributeMetadata(
        "呼ばれている名前", ProfileCategory.IDENTITY_AND_FACE
    ),
    ProfileAttribute.OTHER_SOCIAL_ACCOUNT: ProfileAttributeMetadata(
        "別SNSのアカウント / 本垢",
        ProfileCategory.IDENTITY_AND_FACE,
    ),
    ProfileAttribute.REALTIME_LOCATION: ProfileAttributeMetadata(
        "リアルタイムの現在地",
        ProfileCategory.HOME_AND_LOCATION,
    ),
    ProfileAttribute.HOME_BUILDING: ProfileAttributeMetadata(
        "自宅の建物候補", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.HOME_ROOM: ProfileAttributeMetadata(
        "自宅の部屋・階・位置", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.HOME_NEAREST_STATION: ProfileAttributeMetadata(
        "自宅の最寄り駅", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.REGULAR_STATION: ProfileAttributeMetadata(
        "投稿時点の通勤利用駅候補", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.REGULAR_LINE: ProfileAttributeMetadata(
        "日常的に利用する路線", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.RESIDENTIAL_AREA: ProfileAttributeMetadata(
        "居住エリア（市区町村・町域）",
        ProfileCategory.HOME_AND_LOCATION,
    ),
    ProfileAttribute.ANNOUNCED_LONG_ABSENCE: ProfileAttributeMetadata(
        "予告された長期不在", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.ACTUAL_HOME_ABSENCE: ProfileAttributeMetadata(
        "実際の自宅不在", ProfileCategory.HOME_AND_LOCATION
    ),
    ProfileAttribute.EMPLOYER_NAME: ProfileAttributeMetadata(
        "雇用主名の推定", ProfileCategory.AFFILIATION_AND_WORK
    ),
    ProfileAttribute.WORKPLACE_BUILDING_CANDIDATE: ProfileAttributeMetadata(
        "勤務先建物候補", ProfileCategory.AFFILIATION_AND_WORK
    ),
    ProfileAttribute.WORKPLACE_AREA: ProfileAttributeMetadata(
        "勤務先エリア（オフィス街）",
        ProfileCategory.AFFILIATION_AND_WORK,
    ),
    ProfileAttribute.SCHOOL: ProfileAttributeMetadata(
        "通学先（大学・キャンパス・学校）",
        ProfileCategory.AFFILIATION_AND_WORK,
    ),
    ProfileAttribute.FREQUENT_SHOP: ProfileAttributeMetadata(
        "行きつけの店（ジム・美容院・カフェ）",
        ProfileCategory.ACTIVITY_AND_FAMILY,
    ),
    ProfileAttribute.VEHICLE_MODEL: ProfileAttributeMetadata(
        "自家用車の車種", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
    ProfileAttribute.PARTIAL_PLATE: ProfileAttributeMetadata(
        "ナンバーの一部", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
    ProfileAttribute.PARTNER_STATUS: ProfileAttributeMetadata(
        "配偶者・交際相手の有無", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
    ProfileAttribute.PARTNER_ATTRIBUTES: ProfileAttributeMetadata(
        "配偶者・交際相手の属性", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
    ProfileAttribute.CHILD_AGE: ProfileAttributeMetadata(
        "子どもの年齢", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
    ProfileAttribute.CHILD_SCHOOL: ProfileAttributeMetadata(
        "子どもの通園・通学先", ProfileCategory.ACTIVITY_AND_FAMILY
    ),
}


class ProfileStatus(StrEnum):
    FOUND = "found"
    WEAK = "weak"
    UNKNOWN = "unknown"


class EvidenceSource(StrEnum):
    CLUE = "clue"
    POST_TEXT = "post_text"
    PROFILE_TEXT = "profile_text"
    IMAGE_ALT = "image_alt"
    PUBLIC_WEB = "public_web"


class WebSourceKind(StrEnum):
    OFFICIAL_ORGANIZATION = "official_organization"
    PUBLIC_REGISTRY = "public_registry"
    OTHER = "other"


class WebVerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"
    STALE = "stale"


class ExternalLookupStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    FIXTURE = "fixture"
    SEARCHED = "searched"
    NO_RESULTS = "no_results"
    UNAVAILABLE = "unavailable"


class ExternalProfileStatus(StrEnum):
    CANDIDATE = "candidate"
    OWNER_LINKED = "owner_linked"


class ExternalOwnerEvidenceKind(StrEnum):
    PROFILE_TEXT = "profile_text"
    POST_TEXT = "post_text"


class ExternalOwnerEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ExternalOwnerEvidenceKind
    post_id: str | None = Field(default=None, min_length=1)
    excerpt: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _check_owner_evidence(self) -> Self:
        if self.kind is ExternalOwnerEvidenceKind.PROFILE_TEXT and self.post_id is not None:
            raise ValueError("profile evidence cannot reference a post")
        if self.kind is ExternalOwnerEvidenceKind.POST_TEXT and self.post_id is None:
            raise ValueError("post evidence requires post_id")
        return self


class ExternalProfileResult(BaseModel):
    """A search candidate or a page linked from the owner's own Bluesky profile/post."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    domain: str = Field(min_length=1, max_length=253)
    title: str = Field(min_length=1, max_length=300)
    status: ExternalProfileStatus
    owner_evidence: ExternalOwnerEvidence | None = None

    @model_validator(mode="after")
    def _check_result(self) -> Self:
        from ipaddress import ip_address
        from urllib.parse import urlsplit

        parts = urlsplit(str(self.url))
        host = (parts.hostname or "").lower().rstrip(".")
        labels = host.split(".")
        if parts.scheme != "https" or parts.username is not None or parts.password is not None:
            raise ValueError("external profile URLs require public HTTPS")
        if parts.port not in {None, 443}:
            raise ValueError("external profile URLs require the default HTTPS port")
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("external profile URLs cannot use IP literals")
        if (
            host in {"localhost", "localhost.localdomain"}
            or host.endswith(
                (
                    ".localhost",
                    ".local",
                    ".localdomain",
                    ".internal",
                    ".test",
                    ".invalid",
                    ".home",
                    ".lan",
                    ".home.arpa",
                )
            )
            or len(labels) < 2
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            raise ValueError("external profile URL must use a public hostname")
        if host != self.domain.lower().rstrip("."):
            raise ValueError("external profile domain must match URL host")
        if (self.status is ExternalProfileStatus.OWNER_LINKED) != (self.owner_evidence is not None):
            raise ValueError(
                "owner_linked results require owner evidence; candidates must not have it"
            )
        return self


class WebFact(BaseModel):
    """A public fact about an entity, never a fact about the account owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=200)
    relation: str = Field(min_length=1, max_length=100)
    object: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    source_title: str = Field(min_length=1, max_length=300)
    source_kind: WebSourceKind
    excerpt: str = Field(min_length=1, max_length=500)
    retrieved_at: AwareDatetime
    verification_status: WebVerificationStatus

    @field_validator("source_url")
    @classmethod
    def _require_public_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username is not None or value.password is not None:
            raise ValueError("WebFact source_url requires HTTPS without credentials")
        return value


class ProfileEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str | None = Field(default=None, min_length=1)
    clue_index: NonNegativeInt | None = None
    required: bool
    source: EvidenceSource = EvidenceSource.CLUE
    image_index: NonNegativeInt | None = None
    excerpt: str | None = None
    web_fact_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_source_reference(self) -> Self:
        if self.source is not EvidenceSource.PUBLIC_WEB and self.web_fact_id is not None:
            raise ValueError("only public_web evidence may reference web_fact_id")
        if self.source is EvidenceSource.CLUE:
            if self.post_id is None or self.clue_index is None or self.image_index is not None:
                raise ValueError("clue evidence requires post_id and clue_index")
        elif self.source is EvidenceSource.POST_TEXT:
            if (
                self.post_id is None
                or self.clue_index is not None
                or self.image_index is not None
                or self.excerpt is None
            ):
                raise ValueError("post_text evidence requires post_id and excerpt")
        elif self.source is EvidenceSource.PROFILE_TEXT:
            if self.post_id is not None or self.clue_index is not None or self.excerpt is None:
                raise ValueError("profile_text evidence requires excerpt only")
        elif self.source is EvidenceSource.IMAGE_ALT:
            if (
                self.post_id is None
                or self.clue_index is not None
                or self.image_index is None
                or self.excerpt is None
            ):
                raise ValueError("image_alt evidence requires post_id, image_index, and excerpt")
        elif self.source is EvidenceSource.PUBLIC_WEB and (
            self.web_fact_id is None
            or self.post_id is not None
            or self.clue_index is not None
            or self.image_index is not None
            or self.excerpt is not None
        ):
            raise ValueError("public_web evidence requires only web_fact_id")
        return self


class EvidencePathProvenance(StrEnum):
    DIRECT_DISCLOSURE = "direct_disclosure"
    COMBINED_INFERENCE = "combined_inference"
    UNCLASSIFIED = "unclassified"


class ProfileEvidencePath(BaseModel):
    """One complete conjunction of evidence; paths are alternatives to one another."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: list[ProfileEvidence] = Field(min_length=2)
    confidence: float = Field(ge=0.0, le=1.0)
    # How the candidate value follows from this complete evidence path. A single
    # candidate may have both direct and derived alternative paths.
    provenance: EvidencePathProvenance = EvidencePathProvenance.UNCLASSIFIED


class ProfileRelationKind(StrEnum):
    HOME_NEAREST_IS_COMMUTE_ORIGIN = "home_nearest_is_commute_origin"
    COMMUTE_DESTINATION_IS_EMPLOYER = "commute_destination_is_employer"
    COMMUTE_DESTINATION_IS_SCHOOL = "commute_destination_is_school"


class ProfileRelationEndpointKind(StrEnum):
    PROFILE_CANDIDATE = "profile_candidate"
    COMMUTE_DESTINATION = "commute_destination"


class ProfileRelationEndpoint(BaseModel):
    """A candidate endpoint or a directly stated commute destination."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProfileRelationEndpointKind
    value: str = Field(min_length=1)
    attribute: ProfileAttribute | None = None

    @model_validator(mode="after")
    def _check_attribute(self) -> Self:
        if self.kind is ProfileRelationEndpointKind.PROFILE_CANDIDATE and self.attribute is None:
            raise ValueError("profile candidate relation endpoint requires attribute")
        if self.kind is ProfileRelationEndpointKind.COMMUTE_DESTINATION and self.attribute is not None:
            raise ValueError("commute destination relation endpoint has no profile attribute")
        return self


class ProfileRelation(BaseModel):
    """Evidence-backed link between existing candidates and an explicit commute relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProfileRelationKind
    left: ProfileRelationEndpoint
    right: ProfileRelationEndpoint
    evidence_paths: list[ProfileEvidencePath] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_endpoints(self) -> Self:
        endpoints = (self.left, self.right)
        candidates = [endpoint for endpoint in endpoints
                      if endpoint.kind is ProfileRelationEndpointKind.PROFILE_CANDIDATE]
        destinations = [endpoint for endpoint in endpoints
                        if endpoint.kind is ProfileRelationEndpointKind.COMMUTE_DESTINATION]
        if self.kind is ProfileRelationKind.HOME_NEAREST_IS_COMMUTE_ORIGIN:
            if len(candidates) != 2 or destinations:
                raise ValueError("home-to-commute relation requires two candidate endpoints")
            attrs = {endpoint.attribute for endpoint in candidates}
            values = {endpoint.value for endpoint in candidates}
            if attrs != {ProfileAttribute.HOME_NEAREST_STATION, ProfileAttribute.REGULAR_STATION} or len(values) != 1:
                raise ValueError("home-to-commute relation requires the same station candidate")
        else:
            expected = (ProfileAttribute.EMPLOYER_NAME if self.kind is ProfileRelationKind.COMMUTE_DESTINATION_IS_EMPLOYER
                        else ProfileAttribute.SCHOOL)
            if len(candidates) != 1 or len(destinations) != 1:
                raise ValueError("commute destination relation requires one destination and one candidate")
            if candidates[0].attribute is not expected or candidates[0].value != destinations[0].value:
                raise ValueError("commute destination must exactly match the linked affiliation candidate")
        return self


class EvidenceScope(StrEnum):
    BLUESKY = "bluesky"
    BLUESKY_PUBLIC_WEB = "bluesky_plus_public_web"
    BLUESKY_OFFLINE = "bluesky_plus_offline"


class RatingBasis(StrEnum):
    PROVISIONAL = "provisional"
    MEASURED = "measured"


class HarmStatus(StrEnum):
    APPLICABLE = "applicable"
    PREREQUISITES_UNMET = "prerequisites_unmet"
    UNKNOWN = "unknown"


class ClaimAssessment(BaseModel):
    """Claim/path classification; ratings remain null until evidenced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimal_scope: EvidenceScope | None = None
    offline_subtype: str | None = None
    psychological_resistance: int | None = Field(default=None, ge=1, le=5)
    persona_context: str | None = None
    inference_ease: int | None = Field(default=None, ge=1, le=5)
    inference_ease_basis: RatingBasis | None = None
    harm_severity: int | None = Field(default=None, ge=1, le=5)
    harm_scenario: str | None = None
    harm_prerequisites: list[str] = Field(default_factory=list)
    harm_status: HarmStatus = HarmStatus.UNKNOWN

    @model_validator(mode="after")
    def _check_assessment_consistency(self) -> Self:
        if self.minimal_scope is EvidenceScope.BLUESKY_OFFLINE:
            if not self.offline_subtype or not self.offline_subtype.strip():
                raise ValueError("offline scope requires offline_subtype")
        elif self.offline_subtype is not None:
            raise ValueError("offline_subtype is only valid for bluesky_plus_offline")
        if self.psychological_resistance is not None and not self.persona_context:
            raise ValueError("psychological_resistance requires persona_context")
        if (self.inference_ease is None) != (self.inference_ease_basis is None):
            raise ValueError("inference_ease and its basis must be set together")
        if self.harm_status is HarmStatus.APPLICABLE:
            if self.harm_severity is None or not self.harm_scenario or not self.harm_prerequisites:
                raise ValueError("applicable harm requires severity, scenario, and prerequisites")
        elif self.harm_status is HarmStatus.PREREQUISITES_UNMET:
            if (
                not self.harm_scenario
                or not self.harm_prerequisites
                or self.harm_severity is not None
            ):
                raise ValueError(
                    "unmet harm requires scenario and prerequisites, without asserting severity"
                )
        elif self.harm_severity is not None:
            raise ValueError("harm severity is only set when prerequisites are applicable")
        return self


class ProfileItem(BaseModel):
    """プロフィール出力の型。confidence は校正済み確率を意味しない。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: ProfileAttribute
    value: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    status: ProfileStatus
    evidence: list[ProfileEvidence]
    evidence_paths: list[ProfileEvidencePath] = Field(default_factory=list)
    assessment: ClaimAssessment = Field(default_factory=ClaimAssessment)

    @model_validator(mode="after")
    def _check_value_for_status(self) -> Self:
        if self.status is ProfileStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("unknown の value は null にすること")
        elif self.value is None or not self.value.strip():
            raise ValueError("found / weak の value は空でない文字列にすること")
        return self


class ProfileCandidate(BaseModel):
    """One grounded value candidate within a profile attribute."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: PositiveInt
    value: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    status: ProfileStatus
    evidence: list[ProfileEvidence]
    evidence_paths: list[ProfileEvidencePath] = Field(default_factory=list)
    assessment: ClaimAssessment = Field(default_factory=ClaimAssessment)
    observed_at: AwareDatetime | None = None
    counter_evidence: list[ProfileEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        if self.status is ProfileStatus.UNKNOWN:
            raise ValueError("profile candidates must have found or weak status")
        return self


class ProfileCandidateSetStatus(StrEnum):
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class ProfileCandidateSet(BaseModel):
    """Bounded candidate values for one attribute; never an ungrounded guess list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribute: ProfileAttribute
    status: ProfileCandidateSetStatus
    candidates: list[ProfileCandidate] = Field(max_length=3)
    candidate_pool: list[ProfileCandidate] = Field(default_factory=list)
    conflicting_evidence: list[ProfileEvidence] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def _check_candidates(self) -> Self:
        if any(not candidate.evidence_paths for candidate in self.candidates):
            raise ValueError("profile candidates require at least one complete evidence path")
        if self.attribute is ProfileAttribute.REALTIME_LOCATION:
            if any(candidate.observed_at is None for candidate in self.candidate_pool):
                raise ValueError("realtime location candidates require observed_at")
        elif any(candidate.observed_at is not None for candidate in self.candidate_pool):
            raise ValueError("observed_at is only valid for realtime_location candidates")
        normalized = [unicodedata.normalize("NFKC", c.value).lower().strip() for c in self.candidates]
        if len(normalized) != len(set(normalized)):
            raise ValueError("profile candidate values must be distinct")
        pool_normalized = [unicodedata.normalize("NFKC", c.value).lower().strip() for c in self.candidate_pool]
        if len(pool_normalized) != len(set(pool_normalized)):
            raise ValueError("profile candidate pool values must be distinct")
        if [candidate.rank for candidate in self.candidate_pool] != list(range(1, len(self.candidate_pool) + 1)):
            raise ValueError("candidate pool ranks must be contiguous and start at one")
        ranked_pool = sorted(self.candidate_pool, key=lambda candidate: (
            -candidate.confidence, unicodedata.normalize("NFKC", candidate.value).lower().strip()
        ))
        if self.candidate_pool != ranked_pool:
            raise ValueError("candidate pool must be sorted by confidence then normalized value")
        expected_display = []
        if self.candidate_pool:
            strongest = self.candidate_pool[0]
            if strongest.status is ProfileStatus.WEAK:
                expected_display = [candidate for candidate in self.candidate_pool
                                    if candidate.status is ProfileStatus.WEAK][:3]
            else:
                expected_display = [candidate for candidate in self.candidate_pool
                                    if candidate.status is strongest.status
                                    and strongest.confidence - candidate.confidence <= 0.15][:3]
        if self.candidates != expected_display:
            raise ValueError("display candidates must be the top three candidates in the leading grade/score band")
        count = len(self.candidates)
        if self.status is ProfileCandidateSetStatus.CONFLICT and not self.conflicting_evidence:
            raise ValueError("conflict status requires contradictory evidence")
        if count == 0 and self.candidate_pool:
            raise ValueError("unknown/conflict set cannot have a candidate pool")
        if count and not self.candidate_pool:
            raise ValueError("candidate set requires the full eligible candidate pool")
        if count == 0:
            if self.status not in {ProfileCandidateSetStatus.UNKNOWN, ProfileCandidateSetStatus.CONFLICT}:
                raise ValueError("empty candidate set must be unknown or conflict")
            if not self.reason:
                raise ValueError("empty candidate set requires a reason")
            return self
        if self.status is ProfileCandidateSetStatus.CANDIDATE and count != 1:
            raise ValueError("candidate set must contain exactly one candidate")
        if self.status is ProfileCandidateSetStatus.AMBIGUOUS and not 2 <= count <= 3:
            raise ValueError("ambiguous candidate set must contain two or three candidates")
        if self.status not in {ProfileCandidateSetStatus.CANDIDATE, ProfileCandidateSetStatus.AMBIGUOUS}:
            raise ValueError("unknown or conflict candidate set cannot expose candidate values")
        if count > 1:
            grades = {candidate.status for candidate in self.candidates}
            confidences = [candidate.confidence for candidate in self.candidates]
            if len(grades) != 1 or (
                next(iter(grades)) is ProfileStatus.FOUND
                and max(confidences) - min(confidences) > 0.15
            ):
                raise ValueError("ambiguous candidates must share a grade; found candidates must be within 0.15")
        return self
