"""写真を受け取り、手がかりを返す。

写真はリクエスト本文（画像そのもの）で受け取り、メモリ上だけで扱う。
multipart は一定サイズを超えると一時ファイルに書き出すため使わない。
本文はログに出さない。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from tkb_api.config import Settings, get_settings
from tkb_api.mock_data import MOCK_RESPONSE
from tkb_api.schemas import DetectResponse

router = APIRouter(prefix="/api")

MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)


async def _read_image(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "対応していない画像形式です")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "画像が大きすぎます")
        chunks.append(chunk)

    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "画像が空です")
    return b"".join(chunks)


@router.post("/detect")
async def detect(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DetectResponse:
    await _read_image(request)

    if settings.mock_mode:
        return MOCK_RESPONSE

    # 実際の検出は Hack Day 当日に実装する
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "検出はまだ実装されていません")
