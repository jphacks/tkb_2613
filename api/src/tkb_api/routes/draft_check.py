"""下書きから観測した手がかりと、本人の過去投稿の同一手がかりだけを照合する。"""

import base64
import binascii
import json
import unicodedata
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from PIL import Image
from pydantic import ValidationError

from tkb_api.bluesky import BlueskySession, PostsFetcher
from tkb_api.config import Settings, get_settings
from tkb_api.pipeline import demo_extractions, fetch_images
from tkb_api.routes.diagnose import (
    ExtractorFactory,
    _build_extractor,
    _fetch_own_posts,
    _load_demo_posts,
    get_extractor_factory,
    get_fetch_posts,
)
from tkb_api.routes.session import current_session
from tkb_api.schemas import DraftCheckRequest, DraftCheckResponse, DraftEvidence, DraftOverlap
from tkb_common.schemas import Clue, ClueSource, Post, PostImage
from tkb_detect.errors import DetectError
from tkb_detect.extract import Extractor
from tkb_detect.image import prepare_image

router = APIRouter(prefix="/api")
MAX_REQUEST_BYTES = 30 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)


async def _read_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "下書きが大きすぎます")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_request(raw: bytes) -> DraftCheckRequest:
    try:
        parsed: Any = json.loads(raw)
        return DraftCheckRequest.model_validate(parsed)
    except (ValueError, ValidationError, TypeError, RecursionError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "下書きの形式を確認してください"
        ) from None


def _decode_photo(body: DraftCheckRequest) -> bytes | None:
    if body.photo_base64 is None:
        if body.photo_content_type is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "下書きの形式を確認してください"
            )
        return None
    if body.photo_content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "対応していない写真形式です")
    try:
        photo = base64.b64decode(body.photo_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "下書きの形式を確認してください"
        ) from None
    if not photo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "写真が空です")
    if len(photo) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "写真が大きすぎます")
    try:
        with Image.open(BytesIO(photo)) as image:
            actual_type = Image.MIME.get(image.format or "")
        # Pillowの画像デコーダーが形式・内容を検証し、ピクセル数上限も適用する。
        prepare_image(photo)
    except (OSError, DetectError, Image.DecompressionBombError):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "写真を読み取れません"
        ) from None
    if actual_type != body.photo_content_type:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "写真の形式が一致しません")
    return photo


def _value_key(clue: Clue) -> tuple[str, str]:
    # 同じ type の、同じ表記（Unicode幅・空白・英字大小のみ正規化）を照合する。
    value = " ".join(unicodedata.normalize("NFKC", clue.value).casefold().split())
    return clue.type.value, value


def _mock_draft_check(
    text: str, has_photo: bool, posts: list[Post], settings: Settings
) -> DraftCheckResponse:
    """固定fixtureの本文手がかりを、正規化した下書き本文の部分文字列と照合する。写真は読まない。"""
    by_id = {post.post_id: post for post in posts}
    history: dict[tuple[str, str], tuple[Clue, dict[str, DraftEvidence]]] = {}
    for extraction in demo_extractions(settings.demo_fixture_path, posts):
        post = by_id[extraction.post_id]
        for clue in extraction.clues:
            if clue.source is not ClueSource.TEXT:
                continue
            key = _value_key(clue)
            if len(key[1]) < 2:
                continue
            evidence_by_post = history.setdefault(key, (clue, {}))[1]
            evidence_by_post[post.post_id] = DraftEvidence(
                post_id=post.post_id,
                created_at=post.created_at.isoformat(),
            )

    normalized_text = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    overlaps: list[DraftOverlap] = []
    for key, (source_clue, evidence) in history.items():
        value = key[1]
        if value not in normalized_text:
            continue
        overlaps.append(
            DraftOverlap(
                clue=source_clue.model_copy(
                    update={"post_id": "draft:ephemeral", "confidence": 1.0}
                ),
                evidence=list(evidence.values()),
            )
        )
    notices = [
        "モックでは固定された架空投稿の本文手がかりを、正規化した文字列どうしの部分一致で照合します。これは下書きの抽出結果ではなく、意味は判定しません。"
    ]
    if has_photo:
        notices.append("モックでは写真を解析していません。写真の手がかりは結果に含まれません。")
    return DraftCheckResponse(
        posts_checked=len(posts),
        overlaps=overlaps,
        mock_mode=True,
        notices=notices,
    )


async def _extract(extractor: Extractor, post: Post, photo: bytes | None) -> list[Clue]:
    return await extractor.extract_post(post, [photo] if photo is not None else [])


@router.post("/draft-check", response_model=DraftCheckResponse)
async def check_draft(
    request: Request,
    session: Annotated[BlueskySession, Depends(current_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    fetch_posts: Annotated[PostsFetcher, Depends(get_fetch_posts)],
    extractor_factory: Annotated[ExtractorFactory, Depends(get_extractor_factory)],
) -> DraftCheckResponse:
    """本文/写真はメモリ上で扱い、推理ルールを呼ばず観測手がかりだけ比較する。"""
    body = _parse_request(await _read_body(request))
    photo = _decode_photo(body)
    if not body.text.strip() and photo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "本文か写真を入れてください")
    if settings.mock_mode:
        # canned mock と下書きの抽出結果を混同しないよう、本文の正規化文字列だけを
        # 部分照合する。
        posts = _load_demo_posts(settings)
        return _mock_draft_check(body.text, photo is not None, posts, settings)
    posts = [
        post
        for post in await _fetch_own_posts(session, settings, fetch_posts)
        if post.post_id.startswith(f"at://{session.did}/")
    ]
    extractor = _build_extractor(extractor_factory)

    draft_images: list[PostImage] = []
    if photo is not None:
        # この URL は Post 型を満たすための一時値。取得には使わず、bytes を直接 extractor に渡す。
        draft_images = [
            PostImage(
                index=0,
                url="https://cdn.bsky.app/img/feed_fullsize/draft",
                alt="",
                width=1,
                height=1,
            )
        ]
    draft = Post(
        post_id="draft:ephemeral",
        text=body.text,
        created_at=datetime.now(UTC),  # 抽出器入力の必須項目。推理には渡さない。
        images=draft_images,
    )
    try:
        draft_clues = await _extract(extractor, draft, photo)
        history_clues: list[Clue] = []
        for post in posts:
            images = await fetch_images(post) if post.images else []
            history_clues.extend(await extractor.extract_post(post, images))
    except DetectError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "手がかりを読み取れませんでした") from None
    except Exception:
        # 本文、画像、モデル応答、URL をエラーやログに含めない。
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "下書きを確認できませんでした") from None

    posts_by_id = {post.post_id: post for post in posts}
    evidence: dict[tuple[str, str], dict[str, DraftEvidence]] = {}
    for clue in history_clues:
        source_post = posts_by_id.get(clue.post_id)
        if source_post is None:
            continue
        evidence.setdefault(_value_key(clue), {})[clue.post_id] = DraftEvidence(
            post_id=clue.post_id, created_at=source_post.created_at.isoformat()
        )
    overlaps: list[DraftOverlap] = []
    seen: set[tuple[str, str]] = set()
    for clue in draft_clues:
        key = _value_key(clue)
        found = evidence.get(key)
        if not found or key in seen:
            continue
        seen.add(key)
        overlaps.append(DraftOverlap(clue=clue, evidence=list(found.values())))
    return DraftCheckResponse(
        posts_checked=len(posts), overlaps=overlaps, mock_mode=False, notices=[]
    )
