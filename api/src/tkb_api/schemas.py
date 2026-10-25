"""api の形式。

共有の型（手がかりなど）の正は common/（tkb_common.schemas）で、ここは互換のために読み込み直すだけ。
api の入出力（ログインなど）はこのファイルが Python 側の正。
ログインは web/src/types/session.ts と同時に変更すること。
"""

from typing import Annotated

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
    "DeleteRequest",  # api の入出力
    "DetectResponse",
    "NonNegativeInt",
    "Region",
    # api の入出力
    "SessionRequest",
    "SessionResponse",
    "SimulateRequest",
]

API_ONLY_NAMES = frozenset(
    {"DeleteRequest", "SessionRequest", "SessionResponse", "SimulateRequest"}
)

# 消したらどうなるかで一度に選べる投稿の数（診断する投稿の上限 MAX_POSTS の設定上限と同じ）
SIMULATE_MAX_POSTS = 100
# 一度に実際に消せる投稿の数。提案は最大 3 件なので、多めに取っておく
DELETE_MAX_POSTS = 10


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


class SimulateRequest(BaseModel):
    """消したらどうなるか（POST /api/simulate）。web/src/types/simulate.ts と同時に変更すること。

    delete は、そのセッションで最後に診断した投稿の ID だけ。実際には消さない。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    delete: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        max_length=SIMULATE_MAX_POSTS
    )


class DeleteRequest(BaseModel):
    """投稿を実際に消す（POST /api/delete）。web/src/lib/api.ts の deletePosts と同時に変えること。

    delete は、そのセッションで最後に診断した投稿の ID だけ。画面で選んで確認したものだけを送る。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    delete: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        min_length=1, max_length=DELETE_MAX_POSTS
    )
