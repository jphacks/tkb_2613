"""画面が出し分ける機能のオン・オフ。ログインなしで読める（秘密の値は入れない）。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from tkb_api.config import Settings, get_settings

router = APIRouter(prefix="/api")


@router.get("/features")
def read_features(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, bool | str]:
    return {
        "share_enabled": settings.share_enabled,
        "auth_mode": settings.auth_mode,
        # 真偽値だけを返す。BRAVE_SEARCH_API_KEY の値や長さは返さない
        "public_web_lookup_available": settings.public_web_lookup_available,
    }
