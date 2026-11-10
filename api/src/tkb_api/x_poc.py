"""X の本人投稿を共通 Post に変換する、読み取り専用 PoC。

有料 API を誤って呼ばないよう、コマンド実行入口は置かない。呼び出し側は
X の分析用途の承認と費用の承認を確認した後でだけ fetch_own_posts を呼ぶ。
"""

from typing import Any

import httpx
from pydantic import ValidationError

from tkb_common.schemas import Post

X_API = "https://api.x.com"
MAX_POSTS = 30


class XPocError(Exception):
    """トークンや API 応答本文を含まないエラー。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise XPocError("X API の応答形式が不正です")
    return value


async def _get(
    client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return _object(response.json())
    except httpx.HTTPStatusError as exc:
        raise XPocError(
            f"X API が HTTP {exc.response.status_code} を返しました",
            exc.response.status_code,
        ) from None
    except (httpx.RequestError, ValueError):
        raise XPocError("X API の取得または応答の解析に失敗しました") from None


def to_post(item: dict[str, Any], owner_id: str) -> Post | None:
    """本人が書いた本文付き投稿だけを、画像なしの共通型へ変換する。"""
    if item.get("author_id") != owner_id:
        raise XPocError("本人以外の投稿が応答に含まれました")
    text = item.get("text")
    if not isinstance(text, str):
        raise XPocError("X 投稿の形式が不正です")
    if not text.strip():
        return None
    post_id = item.get("id")
    created_at = item.get("created_at")
    if not isinstance(post_id, str) or not post_id.isascii() or not post_id.isdecimal():
        raise XPocError("X 投稿 ID の形式が不正です")
    if not isinstance(created_at, str):
        raise XPocError("X 投稿の日時が不正です")
    try:
        return Post.model_validate(
            {"post_id": f"x:{post_id}", "text": text, "created_at": created_at, "images": []}
        )
    except ValidationError:
        raise XPocError("X 投稿の日時が不正です") from None


async def fetch_own_posts(token: str, limit: int = MAX_POSTS) -> tuple[str, list[Post]]:
    """OAuth 2.0 User Access Token の /me から得た ID に限定して投稿を読む。

    この関数を実 API で呼ぶと課金されうる。請求額と X の用途承認を先に確認すること。
    """
    if not token.strip():
        raise XPocError("X の OAuth 2.0 User Access Token が設定されていません")
    if not 1 <= limit <= 100:
        raise ValueError("limit は 1〜100 にしてください")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=X_API, headers=headers, timeout=20, follow_redirects=False, trust_env=False
    ) as client:
        profile = await _get(client, "/2/users/me")
        owner_id = _object(profile.get("data")).get("id")
        if not isinstance(owner_id, str) or not owner_id.isascii() or not owner_id.isdecimal():
            raise XPocError("X の本人 ID を確認できませんでした")

        return owner_id, await _fetch_posts(client, owner_id, limit)


async def get_my_user(token: str) -> tuple[str, str]:
    """認証された本人の ID とユーザー名だけを返す。User Read の課金対象。"""
    if not token.strip():
        raise XPocError("X の OAuth 2.0 User Access Token が設定されていません")
    async with httpx.AsyncClient(
        base_url=X_API,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        data = _object((await _get(client, "/2/users/me")).get("data"))
    owner_id, username = data.get("id"), data.get("username")
    if not isinstance(owner_id, str) or not owner_id.isascii() or not owner_id.isdecimal():
        raise XPocError("X の本人 ID を確認できませんでした")
    if not isinstance(username, str) or not username:
        raise XPocError("X の本人名を確認できませんでした")
    return owner_id, username


async def fetch_posts_for_owner(token: str, owner_id: str, limit: int = MAX_POSTS) -> list[Post]:
    """認証時に /me で確認した本人 ID に限り、本文付き投稿を取得する。"""
    if not token.strip() or not owner_id.isascii() or not owner_id.isdecimal():
        raise XPocError("X の本人確認情報が不正です")
    if not 1 <= limit <= 100:
        raise ValueError("limit は 1〜100 にしてください")
    async with httpx.AsyncClient(
        base_url=X_API,
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        return await _fetch_posts(client, owner_id, limit)


async def _fetch_posts(client: httpx.AsyncClient, owner_id: str, limit: int) -> list[Post]:
    posts: list[Post] = []
    # X は返されたリソースに課金する。本文なしや重複があっても読み取り件数を増やさない。
    read_budget = max(5, limit)  # API の max_results は最低 5
    resources_read = 0
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    while resources_read < read_budget:
        remaining = read_budget - resources_read
        if remaining < 5:
            break
        params: dict[str, Any] = {
            "max_results": remaining,
            "post.fields": "author_id,created_at",
            "exclude": "retweets",
        }
        if cursor is not None:
            params["pagination_token"] = cursor
        page = await _get(client, f"/2/users/{owner_id}/tweets", params)
        items = page.get("data", [])
        if not isinstance(items, list):
            raise XPocError("X の投稿一覧の形式が不正です")
        resources_read += len(items)
        for raw in items:
            post = to_post(_object(raw), owner_id)
            if post is not None and post.post_id not in seen_ids:
                posts.append(post)
                seen_ids.add(post.post_id)
                if len(posts) == limit:
                    break
        meta = page.get("meta")
        next_cursor = meta.get("next_token") if isinstance(meta, dict) else None
        if not isinstance(next_cursor, str) or not next_cursor or not items or len(posts) >= limit:
            break
        if next_cursor in seen_cursors:
            raise XPocError("X のページ送りが繰り返されました")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return posts
