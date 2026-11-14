"""Threads テスターの本人投稿をローカルで診断する読み取り専用 PoC。

実行: THREADS_ACCESS_TOKEN を環境変数に設定して uv run python -m tkb_api.threads_poc
トークン、投稿本文、推定値は標準出力にもログにも出さない。
"""

import asyncio
import io
import ipaddress
import logging
import os
import socket
import ssl
import sys
import warnings
from typing import Any

import httpcore
import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from tkb_api.config import get_settings
from tkb_api.pipeline import diagnose_events, load_gazetteer, real_extractions
from tkb_common.schemas import THREADS_MEDIA_HOST_SUFFIXES, Post
from tkb_detect.batch import extract_posts
from tkb_detect.extract import build_extractor

THREADS_API = "https://graph.threads.com/v1.0"
MAX_POSTS = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


class ThreadsPocError(Exception):
    """応答本文やトークンを含まない、利用者向けのエラー。"""


def _is_threads_media_host(host: str) -> bool:
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in THREADS_MEDIA_HOST_SUFFIXES
    )


def _checked_threads_image_url(value: str) -> str | None:
    """443番のMeta CDNだけを許可し、認証情報を埋め込んだURLは拒否する。"""
    try:
        parsed = httpx.URL(value)
    except (TypeError, ValueError):
        return None
    host = parsed.host
    if (
        parsed.scheme != "https"
        or not host
        or not _is_threads_media_host(host)
        or parsed.port not in {None, 443}
        or parsed.userinfo
        or parsed.fragment
    ):
        return None
    return str(parsed)


def _resolved_public_ips(host: str, port: int) -> tuple[str, ...]:
    """DNS応答を1回だけ取得し、非公開アドレスが1件でもあれば全体を拒否する。"""
    if port != 443 or not _is_threads_media_host(host):
        raise OSError("Threads media destination rejected")
    infos = socket.getaddrinfo(
        host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise OSError("Threads media destination rejected")
    return addresses


class _PinnedPublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """検査済みDNS応答へ接続を固定し、接続時の再解決を避ける。"""

    def __init__(self) -> None:
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await asyncio.to_thread(_resolved_public_ips, host, port)
        except (OSError, ValueError):
            raise httpcore.ConnectError("Threads media destination rejected") from None
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.NetworkError as exc:
                last_error = exc
        raise httpcore.ConnectError("Threads media connection failed") from last_error

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Any = None
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise httpcore.ConnectError("Threads media destination rejected")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _threads_media_transport() -> httpx.AsyncHTTPTransport:
    """プロキシを使わず、TLSのSNIは許可済みCDNホストのまま接続する。"""
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl.create_default_context(),
        max_connections=4,
        max_keepalive_connections=0,
        network_backend=_PinnedPublicNetworkBackend(),
    )
    return transport


def _validate_image_bytes(data: bytes) -> None:
    """モデル処理前に画像実体・破損・画素数を検査する。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (
                    image.format not in ALLOWED_IMAGE_FORMATS
                    or image.width < 1
                    or image.height < 1
                    or image.width * image.height > MAX_IMAGE_PIXELS
                ):
                    raise ThreadsPocError("Threads の画像形式を確認できませんでした")
                image.verify()
    except ThreadsPocError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, Warning):
        raise ThreadsPocError("Threads の画像形式を確認できませんでした") from None


class _ThreadsMediaLogFilter(logging.Filter):
    """httpxの任意ログから署名付きMeta CDN URLを除く。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            record.msg == 'HTTP Request: %s %s "%s %d %s"'
            and isinstance(args, tuple)
            and len(args) == 5
            and _checked_threads_image_url(str(args[1])) is not None
        ):
            clean = list(args)
            clean[1] = "https://threads-media.invalid/[redacted]"
            record.args = tuple(clean)
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(item, _ThreadsMediaLogFilter) for item in _httpx_logger.filters):
    _httpx_logger.addFilter(_ThreadsMediaLogFilter())


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ThreadsPocError("Threads API の応答形式が不正です")
    return value


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return _object(response.json())
    except httpx.HTTPStatusError as exc:
        raise ThreadsPocError(
            f"Threads API が HTTP {exc.response.status_code} を返しました"
        ) from None
    except (httpx.RequestError, ValueError):
        raise ThreadsPocError("Threads API の取得または応答の解析に失敗しました") from None


def _threads_image_url(item: dict[str, Any], include_image: bool) -> str | None:
    if not include_image or item.get("media_type") != "IMAGE":
        return None
    value = item.get("media_url")
    if not isinstance(value, str):
        return None
    return _checked_threads_image_url(value)


def to_post(item: dict[str, Any], *, include_image: bool = False) -> Post | None:
    """本文と、明示的に有効な場合だけ単一画像を共通型へ変換する。"""
    text = item.get("text")
    image_url = _threads_image_url(item, include_image)
    if text is not None and not isinstance(text, str):
        raise ThreadsPocError("Threads 投稿の形式が不正です")
    if not isinstance(text, str):
        text = ""
    if not text.strip() and image_url is None:
        return None
    post_id = item.get("id")
    timestamp = item.get("timestamp")
    if not isinstance(post_id, str) or not post_id or not isinstance(timestamp, str):
        raise ThreadsPocError("Threads 投稿の形式が不正です")
    try:
        images = (
            []
            if image_url is None
            else [{"index": 0, "url": image_url, "alt": "", "width": 1, "height": 1}]
        )
        return Post.model_validate(
            {
                "post_id": f"threads:{post_id}",
                "text": text,
                "created_at": timestamp,
                "images": images,
            }
        )
    except ValidationError:
        raise ThreadsPocError("Threads 投稿の日時が不正です") from None


async def fetch_own_posts(
    token: str, limit: int = MAX_POSTS, *, include_images: bool = False
) -> tuple[str, list[Post]]:
    if not token.strip():
        raise ThreadsPocError("THREADS_ACCESS_TOKEN が設定されていません")
    if not 1 <= limit <= 100:
        raise ValueError("limit は 1〜100 にしてください")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=THREADS_API, headers=headers, timeout=20, follow_redirects=False, trust_env=False
    ) as client:
        profile = await _get(client, "/me", {"fields": "id,username"})
        user_id = profile.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise ThreadsPocError("Threads の本人 ID を確認できませんでした")

        posts: list[Post] = []
        seen_ids: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        while len(posts) < limit:
            fields = "id,text,timestamp,media_type"
            if include_images:
                fields += ",media_url"
            params: dict[str, Any] = {
                "fields": fields,
                "limit": min(50, limit - len(posts)),
            }
            if cursor is not None:
                params["after"] = cursor
            page = await _get(client, "/me/threads", params)
            items = page.get("data")
            if not isinstance(items, list):
                raise ThreadsPocError("Threads の投稿一覧の形式が不正です")
            for raw in items:
                post = to_post(_object(raw), include_image=include_images)
                if post is not None and post.post_id not in seen_ids:
                    posts.append(post)
                    seen_ids.add(post.post_id)
                    if len(posts) == limit:
                        break
            paging = page.get("paging")
            cursors = paging.get("cursors") if isinstance(paging, dict) else None
            next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(next_cursor, str) or not next_cursor or not items:
                break
            if next_cursor in seen_cursors:
                raise ThreadsPocError("Threads のページ送りが繰り返されました")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return user_id, posts


async def fetch_threads_images(post: Post) -> list[bytes]:
    """許可済みMeta CDNからThreadsの画像1枚だけをメモリへ取得する。"""
    if len(post.images) > 1:
        raise ThreadsPocError("Threads の画像は1枚だけ診断できます")
    result: list[bytes] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
        trust_env=False,
        transport=_threads_media_transport(),
        headers={"Accept": "image/jpeg,image/png,image/webp"},
    ) as client:
        for image in post.images:
            url = _threads_image_url(
                {"media_type": "IMAGE", "media_url": image.url}, include_image=True
            )
            if url is None:
                raise ThreadsPocError("Threads の画像取得先を確認できませんでした")
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        raise ThreadsPocError("Threads の画像取得先を確認できませんでした")
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
                        raise ThreadsPocError("Threads の画像形式を確認できませんでした")
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            raise ThreadsPocError(
                                "Threads の画像形式を確認できませんでした"
                            ) from None
                        if declared_size < 0 or declared_size > MAX_IMAGE_BYTES:
                            raise ThreadsPocError("Threads の画像が大きすぎます")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ThreadsPocError("Threads の画像が大きすぎます")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    # ここではコンテナ検証だけを行う。20MB・2500万画素で上限済みで、
                    # 完全なデコードと縮小はextractor側で別スレッドに出す。
                    _validate_image_bytes(data)
                    result.append(data)
            except httpx.HTTPError:
                # URLや応答本文は例外・ログへ出さない。
                raise ThreadsPocError("Threads の画像を取得できませんでした") from None
    return result


async def run() -> int:
    token = os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token.strip():
        raise ThreadsPocError("THREADS_ACCESS_TOKEN が設定されていません")
    settings = get_settings()
    _user_id, posts = await fetch_own_posts(token, include_images=settings.threads_image_diagnosis)
    if not posts:
        print("診断対象の本文付き投稿は 0 件です")
        return 0

    extractor = build_extractor(
        mock_mode=False,
        vlm_base_url=settings.vlm_base_url,
        vlm_api_key=settings.vlm_api_key.get_secret_value(),
        vlm_model=settings.vlm_model,
        ocr_base_url=settings.ocr_base_url,
        allowed_hosts=settings.model_allowed_host_suffixes.split(","),
        text_backend=settings.text_backend,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
    )
    gazetteer = load_gazetteer(settings.gazetteer_dir)
    clue_count = conclusion_count = failed = 0
    extractions = (
        extract_posts(
            extractor,
            posts,
            fetch_threads_images,
            image_fetch_fallback_to_text=True,
        )
        if settings.threads_image_diagnosis
        else real_extractions(extractor, posts)
    )
    async for event, data in diagnose_events(posts, extractions, gazetteer):
        if event == "clues":
            failed += data["error"] is not None
        elif event == "conclusions":
            clue_count = len(data["clues"])
            # The main API publishes catalog-driven ProfileCandidateSets, not the
            # internal Conclusion intermediates.
            conclusion_count = len(data["profile_claims"])
        # post / plan の内容は表示しない。plan はメモリ内の仮除外計算だけ。
    print(
        f"Threads 本人 ID を確認。投稿 {len(posts)} 件、手がかり {clue_count} 件、"
        f"推定 {conclusion_count} 件、抽出失敗 {failed} 件。"
    )
    return 1 if failed else 0


def main() -> None:
    try:
        code = asyncio.run(run())
    except ThreadsPocError as exc:
        print(str(exc), file=sys.stderr)
        code = 1
    except Exception:
        # モデル設定や接続の例外にも URL・本文・トークンが混ざる可能性がある。
        print("診断の準備または実行に失敗しました", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
