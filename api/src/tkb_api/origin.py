"""元に戻せない操作の Origin の確認。Cookie の SameSite=Lax に加えて、別のサイトからの送信を断る。

ブラウザは POST・DELETE に Origin を付けるので、Origin がない・許可したオリジンでない要求は 403。
本体（Bluesky）は settings.cors_origins、X・Threads はそれぞれの公開オリジンで確かめる。
"""

from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from tkb_api.config import Settings, get_settings

SAME_SITE_MESSAGE = "同じサイトから操作してください"


def check_origin(request: Request, allowed: Iterable[str]) -> None:
    """Origin が allowed のどれかと同じでなければ 403。末尾の / の有無は区別しない。"""
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in {a.rstrip("/") for a in allowed}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, SAME_SITE_MESSAGE)


def same_origin(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """本体の画面（CORS_ORIGINS）からの要求か。元に戻せない操作のルートに付ける。"""
    check_origin(request, settings.cors_origins)
