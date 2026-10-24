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
    Clue,
    ClueSource,
    ClueType,
    DetectResponse,
    NonNegativeInt,
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
    "DetectResponse",
    "NonNegativeInt",
    "Region",
    # api の入出力
    "SessionRequest",
    "SessionResponse",
]

API_ONLY_NAMES = frozenset({"SessionRequest", "SessionResponse"})


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
