"""api の形式。

共有の型（手がかりなど）の正は common/（tkb_common.schemas）で、ここは互換のために読み込み直すだけ。
api の入出力（ログインなど）はこのファイルが Python 側の正。
ログインは web/src/types/session.ts と同時に変更すること。
"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from tkb_common.schemas import (
    PHOTO_ONLY_TYPES,
    PHOTO_SOURCES,
    TEXT_ONLY_TYPES,
    ClaimAssessment,
    Clue,
    ClueSource,
    ClueType,
    DetectResponse,
    NonNegativeInt,
    ProfileAttribute,
    ProfileEvidence,
    ProfileEvidencePath,
    ProfileItem,
    ProfileStatus,
    Region,
)

__all__ = [
    # tkb_common から読み込み直している共有の型
    "PHOTO_ONLY_TYPES",
    "PHOTO_SOURCES",
    "TEXT_ONLY_TYPES",
    "Clue",
    "ClueSource",
    "ClueType",
    "ClaimAssessment",
    "DetectResponse",
    "ProfileAttribute",
    "ProfileEvidence",
    "ProfileEvidencePath",
    "ProfileItem",
    "ProfileStatus",
    "NonNegativeInt",
    "Region",
    # api の入出力
    "SessionRequest",
    "SessionResponse",
    "DraftCheckRequest",
    "DraftEvidence",
    "DraftOverlap",
    "DraftCheckResponse",
]

API_ONLY_NAMES = frozenset(
    {
        "SessionRequest",
        "SessionResponse",
        "DraftCheckRequest",
        "DraftEvidence",
        "DraftOverlap",
        "DraftCheckResponse",
    }
)


class DraftCheckRequest(BaseModel):
    """投稿前確認。画像はbase64で受け取り、multipartの一時ファイルを避ける。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(max_length=10_000)
    photo_base64: str | None = Field(default=None, max_length=28_000_000)
    photo_content_type: str | None = None


class DraftEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    post_id: str
    created_at: str


class DraftOverlap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clue: Clue
    evidence: list[DraftEvidence]


class DraftCheckResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    posts_checked: int
    overlaps: list[DraftOverlap]
    mock_mode: bool
    notices: list[str]


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
