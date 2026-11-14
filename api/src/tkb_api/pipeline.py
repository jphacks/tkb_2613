"""診断の流れ：投稿 → 手がかりの取り出し（detect）→ 推理（engine）→ 危ない投稿（engine.plan）。

ルート（routes/diagnose.py）から使う。SSE の文字列の組み立てはルートの仕事で、ここは
イベント名と data の組を順に返す。
写真は cdn.bsky.app からメモリに取ってくるだけで、ディスクにもログにも残さない。
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from tkb_api.public_web_identity import ExternalLookupResult
from tkb_common.schemas import (
    BSKY_CDN_PREFIX,
    Clue,
    ExternalLookupStatus,
    ExternalProfileResult,
    PhotoPlaceResult,
    Post,
    ProfileCandidateSet,
    WebFact,
)
from tkb_detect.batch import PostExtraction, extract_posts
from tkb_detect.extract import Extractor
from tkb_engine.cross_post import (
    infer_owner_candidate_sets_with_web,
    infer_owner_profile_relations,
    plan_profile_candidate_deletion,
    recalculate_profile_candidate_sets,
    simulate_profile_candidate_sets,
)
from tkb_engine.gazetteer import Gazetteer, Knowledge
from tkb_engine.narrowing import narrowing
from tkb_engine.photo_place import infer_photo_places
from tkb_engine.planner import Simulation, plan, simulate
from tkb_engine.rules import Conclusion, infer

logger = logging.getLogger(__name__)

BSKY_CDN_HOST = urlparse(BSKY_CDN_PREFIX).hostname
# Bluesky の写真は 1MB 前後。大きすぎるものは読まない
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# 写真の取得の待ち時間は制限しない。つながらないときだけ早めに諦める
IMAGE_FETCH_TIMEOUT = httpx.Timeout(None, connect=10.0)
IMAGE_FETCH_ATTEMPTS = 3

Event = tuple[str, dict[str, Any]]


class ImageFetchError(Exception):
    """写真を取ってこられなかった。URL などの中身は文言に入れない。"""


async def fetch_images(post: Post) -> list[bytes]:
    """投稿の写真を post.images の順に取ってくる。取りに行くのは cdn.bsky.app だけ。"""
    images = []
    async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT, follow_redirects=False) as client:
        for image in post.images:
            url = _checked_image_url(image.url)
            images.append(await _download(client, url))
    return images


async def fetch_single_image(
    post: Post, image_index: int, max_bytes: int = MAX_IMAGE_BYTES
) -> bytes:
    """Fetch exactly one indexed post image from the allowlisted Bluesky CDN."""
    image = next((item for item in post.images if item.index == image_index), None)
    if image is None:
        raise ImageFetchError("写真が見つかりません")
    url = _checked_image_url(image.url)
    async with httpx.AsyncClient(timeout=IMAGE_FETCH_TIMEOUT, follow_redirects=False) as client:
        return await _download(client, url, max_bytes=max_bytes)


def _checked_image_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != BSKY_CDN_HOST:
        raise ImageFetchError("写真の取得先が cdn.bsky.app ではありません")
    return url


async def _download(
    client: httpx.AsyncClient, url: str, *, max_bytes: int = MAX_IMAGE_BYTES
) -> bytes:
    for attempt in range(IMAGE_FETCH_ATTEMPTS):
        try:
            async with client.stream("GET", url) as res:
                res.raise_for_status()
                chunks, size = [], 0
                async for chunk in res.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ImageFetchError("写真が大きすぎます")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as e:
            status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
            retryable = (
                isinstance(e, httpx.RequestError)
                or status_code == 429
                or (status_code is not None and status_code >= 500)
            )
            logger.warning(
                "写真取得失敗: %s status=%s attempt=%d/%d",
                type(e).__name__,
                status_code,
                attempt + 1,
                IMAGE_FETCH_ATTEMPTS,
            )
            if not retryable or attempt + 1 == IMAGE_FETCH_ATTEMPTS:
                raise ImageFetchError(type(e).__name__) from e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


def load_gazetteer(data_dir: Path) -> Gazetteer:
    """data-prep の表と知識表を読む。読めなければ空の表にして、その表を使うルールだけを飛ばす。

    知識表（指定ゴミ袋・収集地区・大学）はリポジトリにあるので、data-prep の表がなくても使う。
    """
    knowledge = load_knowledge()
    try:
        return Gazetteer.load(data_dir, knowledge=knowledge)
    except (OSError, ValueError, KeyError) as e:
        logger.warning(
            "推理の表を読めませんでした（%s）。最寄り駅のルールは使いません", type(e).__name__
        )
        return Gazetteer(knowledge=knowledge)


def load_knowledge() -> Knowledge:
    try:
        return Knowledge.load()
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.warning(
            "知識表を読めませんでした（%s）。市区町村・収集地区・学校のルールは使いません",
            type(e).__name__,
        )
        return Knowledge()


def demo_extractions(fixture_path: Path, posts: Sequence[Post]) -> list[PostExtraction]:
    """MOCK_MODE 用。デモ用データの手がかりを投稿ごとにまとめる（モデルには接続しない）。"""
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    clues = [Clue.model_validate(c) for c in doc["clues"]]
    return [
        PostExtraction(post_id=p.post_id, clues=[c for c in clues if c.post_id == p.post_id])
        for p in posts
    ]


async def _replay(
    extractions: Sequence[PostExtraction], interval: float
) -> AsyncIterator[PostExtraction]:
    for extraction in extractions:
        await asyncio.sleep(interval)
        yield extraction


def _kept_indices(clues: Sequence[Clue], gone: Iterable[str]) -> list[int]:
    """gone の投稿を除いた手がかりが、clues（診断の全手がかり）で何番だったか。"""
    removed = set(gone)
    return [i for i, c in enumerate(clues) if c.post_id not in removed]


def _remaining(
    clues: Sequence[Clue], posts: Sequence[Post], excluded: Iterable[str]
) -> tuple[list[Clue], list[Post]]:
    gone = set(excluded)
    return [c for c in clues if c.post_id not in gone], [p for p in posts if p.post_id not in gone]


def _renumbered(conclusions: Sequence[Conclusion], kept: Sequence[int]) -> list[dict[str, Any]]:
    return [{**asdict(c), "clue_indices": [kept[i] for i in c.clue_indices]} for c in conclusions]


def simulation_json(
    sim: Simulation, clues: Sequence[Clue], excluded: Sequence[str] = ()
) -> dict[str, Any]:
    """Serialize the legacy Conclusion response for the Threads compatibility route."""
    return {
        "delete": sim.delete,
        "broken": sim.broken,
        "after": _renumbered(sim.after, _kept_indices(clues, [*excluded, *sim.delete])),
    }


def simulate_json(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    gazetteer: Gazetteer,
    delete: Sequence[str],
    excluded: Sequence[str] = (),
) -> dict[str, Any]:
    """excluded（もう消した投稿）を除いた状態から、delete を消したらどうなるか。"""
    remaining_clues, remaining_posts = _remaining(clues, posts, excluded)
    sim = simulate(remaining_clues, remaining_posts, gazetteer, delete)
    return simulation_json(sim, clues, excluded)


def plan_json(
    clues: Sequence[Clue],
    posts: Sequence[Post],
    gazetteer: Gazetteer,
    excluded: Sequence[str] = (),
) -> dict[str, Any]:
    """危ない投稿と、それを全部消したときの結果。投稿ごとに、それだけを消したときに崩れる項目も添える。

    excluded（もう消した投稿）は候補にせず、除いた状態から計算する。番号は clues での番号。
    """
    remaining_clues, remaining_posts = _remaining(clues, posts, excluded)
    proposal = plan(remaining_clues, remaining_posts, gazetteer)
    per_post = [
        {
            "post_id": post_id,
            "broken": simulate(remaining_clues, remaining_posts, gazetteer, [post_id]).broken,
        }
        for post_id in proposal.delete
    ]
    return {**simulation_json(proposal, clues, excluded), "posts": per_post}


def simulate_claims_json(
    candidate_sets: Sequence[ProfileCandidateSet],
    clues: Sequence[Clue],
    posts: Sequence[Post],
    delete: Sequence[str],
    excluded: Sequence[str] = (),
    *,
    diagnosis_at: datetime | None = None,
    gazetteer: Gazetteer | None = None,
) -> dict[str, Any]:
    """excluded を除いた状態から、delete を消したときの候補集合の変化を返す。"""
    sim = simulate_profile_candidate_sets(
        candidate_sets,
        posts,
        delete,
        clues=clues,
        excluded_post_ids=excluded,
        diagnosis_at=diagnosis_at,
    )
    result = {
        "delete": sim.delete,
        "broken": sim.broken,
        "after": [item.model_dump(mode="json") for item in sim.after],
    }
    if gazetteer is not None:
        gone = set(excluded) | set(delete)
        _, remaining_posts = _remaining(clues, posts, gone)
        result["narrowing"] = narrowing(clues, remaining_posts, sim.after, gazetteer)
    return result


def plan_claims_json(
    candidate_sets: Sequence[ProfileCandidateSet],
    clues: Sequence[Clue],
    posts: Sequence[Post],
    excluded: Sequence[str] = (),
    *,
    diagnosis_at: datetime | None = None,
    proposed_delete: Sequence[str] | None = None,
) -> dict[str, Any]:
    """候補カタログを基準に、最小削除提案と投稿ごとの影響項目を返す。"""
    _, remaining_posts = _remaining(clues, posts, excluded)
    excluded_set = set(excluded)
    before = (
        recalculate_profile_candidate_sets(
            candidate_sets,
            excluded_set,
            remaining_posts,
            clues=clues,
            diagnosis_at=diagnosis_at,
        )
        if excluded_set
        else list(candidate_sets)
    )
    delete_ids = (
        list(proposed_delete)
        if proposed_delete is not None
        else plan_profile_candidate_deletion(before, remaining_posts)
    )
    proposal = simulate_profile_candidate_sets(
        before,
        remaining_posts,
        delete_ids,
        clues=clues,
        diagnosis_at=diagnosis_at,
    )
    per_post = [
        {
            "post_id": post_id,
            "broken": simulate_profile_candidate_sets(
                before,
                remaining_posts,
                [post_id],
                clues=clues,
                diagnosis_at=diagnosis_at,
            ).broken,
        }
        for post_id in proposal.delete
    ]
    return {
        "delete": proposal.delete,
        "broken": proposal.broken,
        "after": [item.model_dump(mode="json") for item in proposal.after],
        "posts": per_post,
    }


async def diagnose_events(
    posts: Sequence[Post],
    extractions: AsyncIterator[PostExtraction],
    gazetteer: Gazetteer,
    interval: float = 0,
    on_finished: Callable[[list[Clue]], None] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    *,
    owner_profile_text: str = "",
    owner_profile_analyzer: Callable[[str], Awaitable[list[Clue]]] | None = None,
    web_facts: Sequence[WebFact] = (),
    web_lookup_status: str = "not_run",
    external_profile_results: Sequence[ExternalProfileResult] = (),
    external_lookup_status: ExternalLookupStatus = ExternalLookupStatus.NOT_REQUESTED,
    external_lookup: Callable[[], Awaitable[ExternalLookupResult]] | None = None,
    photo_place_lookup: Callable[
        [Sequence[PhotoPlaceResult], Sequence[Clue]], Awaitable[list[PhotoPlaceResult]]
    ]
    | None = None,
    photo_place_reference_lookup: Callable[
        [Sequence[PhotoPlaceResult], Sequence[Clue], Sequence[Post]],
        Awaitable[list[PhotoPlaceResult]],
    ]
    | None = None,
    diagnosis_date: date | None = None,
    diagnosis_at: datetime | None = None,
) -> AsyncIterator[Event]:
    """診断のイベントを順に返す。

    post（投稿ごと）→ clues（手がかりの取り出しが終わった順）→ conclusions（推理）
    → plan（危ない投稿）→ done
    conclusions の clue_indices は、同じイベントの clues の並びでの番号。plan の after も同じ番号。
    on_finished は推理まで終わったときに全手がかりで呼ぶ（セッションに置いて simulate に使う）。

    かかった時間をログに出す（発表の段取りと、写真の数で時間がどう増えるかを見るため）。
    出すのは件数と秒数だけで、投稿の ID・本文・写真の中身は出さない。
    """
    for post in posts:
        yield "post", {"post": post.model_dump(mode="json")}
        await asyncio.sleep(interval)

    images = {p.post_id: len(p.images) for p in posts}
    all_clues: list[Clue] = []
    finished = failed = 0
    started = clock()
    async for extraction in extractions:
        all_clues.extend(extraction.clues)
        finished += 1
        failed += extraction.error is not None
        logger.info(
            "診断 %d/%d 件目：%.1f 秒（写真 %d 枚、手がかり %d 件%s）",
            finished,
            len(posts),
            clock() - started,
            images.get(extraction.post_id, 0),
            len(extraction.clues),
            "、失敗" if extraction.error is not None else "",
        )
        yield "clues", extraction.model_dump(mode="json")
    extracted = clock()

    if external_lookup is not None:
        try:
            lookup_result = await external_lookup()
            external_lookup_status = lookup_result.status
            external_profile_results = lookup_result.results
        except Exception:
            # 外部検索の失敗で診断全体を止めず、例外内容をログ/SSEへ出さない。
            external_lookup_status = ExternalLookupStatus.UNAVAILABLE
            external_profile_results = ()

    # 推理と危ない投稿の選び方は CPU を使うので、別のスレッドで行う
    # （診断中も、ほかの人の応答と SSE の keep-alive を止めない）
    conclusions = await asyncio.to_thread(infer, all_clues, list(posts), gazetteer)
    photo_place_results = await asyncio.to_thread(
        infer_photo_places, list(posts), all_clues, gazetteer
    )
    if photo_place_reference_lookup is not None:
        try:
            photo_place_results = await photo_place_reference_lookup(
                photo_place_results, all_clues, posts
            )
        except Exception:
            # Optional lookup failures never stop diagnosis; exception text can contain coordinates.
            from tkb_api.commons_reference import mark_reference_lookup_unavailable

            photo_place_results = mark_reference_lookup_unavailable(
                photo_place_results, all_clues, gazetteer
            )
    if photo_place_lookup is not None:
        try:
            photo_place_results = await photo_place_lookup(photo_place_results, all_clues)
        except Exception:
            # External failure must not stop local inference or leak query values.
            from tkb_api.photo_place_web import mark_photo_place_lookup_unavailable

            photo_place_results = mark_photo_place_lookup_unavailable(
                photo_place_results, all_clues, "photo_place_search_unavailable"
            )
    self_report_clues = (
        await owner_profile_analyzer(owner_profile_text)
        if owner_profile_text and owner_profile_analyzer
        else []
    )
    profile_claims = infer_owner_candidate_sets_with_web(
        list(posts),
        all_clues,
        list(web_facts),
        owner_profile_text,
        self_report_clues,
        gazetteer=gazetteer,
        diagnosis_date=diagnosis_date,
        diagnosis_at=diagnosis_at,
        photo_place_results=photo_place_results,
        rule_conclusions=conclusions,
    )
    profile_claim_suggestions = plan_profile_candidate_deletion(profile_claims, posts)
    profile_relations = infer_owner_profile_relations(
        list(posts),
        profile_claims,
        clues=all_clues,
        gazetteer=gazetteer,
        rule_conclusions=conclusions,
    )
    narrowing_result = narrowing(all_clues, list(posts), profile_claims, gazetteer)
    yield (
        "conclusions",
        {
            "clues": [c.model_dump(mode="json") for c in all_clues],
            "photo_place_results": [item.model_dump(mode="json") for item in photo_place_results],
            "profile_claims": [item.model_dump(mode="json") for item in profile_claims],
            "narrowing": narrowing_result,
            "profile_relations": [item.model_dump(mode="json") for item in profile_relations],
            "profile_claim_suggestions": profile_claim_suggestions,
            "web_facts": [fact.model_dump(mode="json") for fact in web_facts],
            "web_lookup_status": web_lookup_status,
            "external_profile_results": [
                result.model_dump(mode="json") for result in external_profile_results
            ],
            "external_lookup_status": external_lookup_status.value,
            "self_report_clues": [c.model_dump(mode="json") for c in self_report_clues],
            # Direct self-report is kept separate from cross-post inference and streamed only
            # to the authenticated owner; it is never persisted.
            "owner_profile_text": owner_profile_text,
        },
    )
    if on_result is not None:
        on_result(
            {
                "clues": all_clues,
                "photo_place_results": photo_place_results,
                "profile_claims": profile_claims,
                "profile_relations": profile_relations,
                "profile_claim_suggestions": profile_claim_suggestions,
                "web_facts": list(web_facts),
                "web_lookup_status": web_lookup_status,
                "external_profile_results": list(external_profile_results),
                "external_lookup_status": external_lookup_status,
                "owner_profile_text": owner_profile_text,
                "self_report_clues": self_report_clues,
            }
        )
    yield (
        "plan",
        await asyncio.to_thread(
            plan_claims_json,
            profile_claims,
            all_clues,
            posts,
            diagnosis_at=diagnosis_at,
            proposed_delete=profile_claim_suggestions,
        ),
    )
    logger.info(
        "診断の時間：手がかりの取り出し %.1f 秒"
        "（投稿 %d 件、写真 %d 枚、手がかり %d 件、失敗 %d 件）、推理と危ない投稿 %.2f 秒",
        extracted - started,
        len(posts),
        sum(images.values()),
        len(all_clues),
        failed,
        clock() - extracted,
    )
    if on_finished is not None:
        on_finished(all_clues)
    yield "done", {"posts_seen": len(posts)}


def real_extractions(extractor: Extractor, posts: Sequence[Post]) -> AsyncIterator[PostExtraction]:
    return extract_posts(extractor, posts, fetch_images)


def mock_extractions(
    fixture_path: Path, posts: Sequence[Post], interval: float
) -> AsyncIterator[PostExtraction]:
    return _replay(demo_extractions(fixture_path, posts), interval)
