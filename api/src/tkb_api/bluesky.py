"""Bluesky へのログインと、ログイン中のセッション、自分の投稿の取得。

パスワードはログインに使うだけで、保存もログ出力もしない。
セッションはメモリ上だけに置き、ブラウザにはランダムなセッション番号だけを渡す。
投稿はセッションの DID のものだけを取る（他人のアカウントは指定できない）。
"""

import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from atproto import AsyncClient, models
from atproto_client.exceptions import AtProtocolError, BadRequestError, UnauthorizedError
from pydantic import ValidationError

from tkb_common.schemas import Post, PostImage

# 自分の投稿が limit 件そろうまでにタイムラインをたどるページ数の上限（リポストが多い人向け）
MAX_FEED_PAGES = 3
FEED_PAGE_SIZE = 100


class LoginFailedError(Exception):
    """ハンドル名かパスワードが違う。"""


class BlueskyUnavailableError(Exception):
    """Bluesky に接続できない、または想定外の応答。"""


@dataclass(frozen=True)
class LoginResult:
    handle: str
    did: str
    # モックのときは None（外部に一切接続しない）
    client: AsyncClient | None


LoginFn = Callable[[str, str], Awaitable[LoginResult]]


async def login(handle: str, password: str, service: str = "https://bsky.social") -> LoginResult:
    client = AsyncClient(base_url=f"{service.rstrip('/')}/xrpc")
    try:
        me = await client.login(handle, password)
    except (UnauthorizedError, BadRequestError) as e:
        raise LoginFailedError from e
    except AtProtocolError as e:
        raise BlueskyUnavailableError from e
    if me is None:
        raise BlueskyUnavailableError
    return LoginResult(handle=me.handle, did=me.did, client=client)


PostsFetcher = Callable[[AsyncClient, str, int], Awaitable[list[Post]]]


def _images_of(embed: object) -> list[models.AppBskyEmbedImages.ViewImage]:
    if isinstance(embed, models.AppBskyEmbedImages.View):
        return list(embed.images)
    if isinstance(embed, models.AppBskyEmbedRecordWithMedia.View) and isinstance(
        embed.media, models.AppBskyEmbedImages.View
    ):
        return list(embed.media.images)
    return []


def to_post(item: models.AppBskyFeedDefs.FeedViewPost, did: str) -> Post | None:
    """タイムラインの 1 件を Post にする。リポスト、他人の投稿、形の合わないものは None。"""
    view = item.post
    if item.reason is not None or view.author.did != did:
        return None
    record = view.record
    if not isinstance(record, models.AppBskyFeedPost.Record):
        return None

    images: list[PostImage] = []
    for image in _images_of(view.embed):
        # 縦横の大きさが付いていない写真は、手がかりの位置を描けないので外す
        if image.aspect_ratio is None:
            continue
        try:
            images.append(
                PostImage(
                    index=len(images),
                    url=image.fullsize,
                    alt=image.alt,
                    width=image.aspect_ratio.width,
                    height=image.aspect_ratio.height,
                )
            )
        except ValidationError:
            continue

    try:
        return Post(post_id=view.uri, text=record.text, created_at=record.created_at, images=images)
    except ValidationError:
        return None


async def fetch_own_posts(client: AsyncClient, did: str, limit: int) -> list[Post]:
    """did 本人の投稿を新しい順に limit 件まで取る。"""
    posts: list[Post] = []
    cursor: str | None = None
    for _ in range(MAX_FEED_PAGES):
        try:
            res = await client.get_author_feed(actor=did, cursor=cursor, limit=FEED_PAGE_SIZE)
        except AtProtocolError as e:
            raise BlueskyUnavailableError from e
        for item in res.feed:
            post = to_post(item, did)
            if post is None:
                continue
            posts.append(post)
            if len(posts) == limit:
                return posts
        cursor = res.cursor
        if not cursor:
            break
    return posts


@dataclass(frozen=True)
class BlueskySession:
    handle: str
    did: str
    client: AsyncClient | None
    expires_at: float


class SessionStore:
    """セッション番号 → ログイン中のセッション。メモリ上だけに置き、期限が来たら捨てる。"""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._sessions: dict[str, BlueskySession] = {}

    def create(self, result: LoginResult) -> str:
        self._purge_expired()
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = BlueskySession(
            handle=result.handle,
            did=result.did,
            client=result.client,
            expires_at=self._clock() + self._ttl,
        )
        return session_id

    def get(self, session_id: str) -> BlueskySession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expires_at <= self._clock():
            del self._sessions[session_id]
            return None
        return session

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        return len(self._sessions)

    def _purge_expired(self) -> None:
        now = self._clock()
        for session_id in [k for k, v in self._sessions.items() if v.expires_at <= now]:
            del self._sessions[session_id]
