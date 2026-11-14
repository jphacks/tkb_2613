import pytest

from tkb_api import threads_verify
from tkb_api.threads_verify import Counts, format_counts, strip_images, summarize
from tkb_common.schemas import Clue, ClueSource, ClueType, Post
from tkb_detect.batch import PostExtraction
from tkb_detect.extract import Extractor

SECRET_TEXT = "秘密の本文ABC"  # noqa: S105
SECRET_URL = "https://scontent.cdninstagram.com/secret.jpg?token=must-not-print"  # noqa: S105
SECRET_TOKEN = "tok-must-not-print"  # noqa: S105


def _post(post_id: str, *, image: bool) -> Post:
    images = [{"index": 0, "url": SECRET_URL, "alt": "", "width": 1, "height": 1}] if image else []
    return Post.model_validate(
        {
            "post_id": f"threads:{post_id}",
            "text": SECRET_TEXT,
            "created_at": "2026-11-10T00:00:00Z",
            "images": images,
        }
    )


def _clue(post_id: str, image_index: int | None) -> Clue:
    return Clue(
        post_id=post_id,
        image_index=image_index,
        type=ClueType.SHOP if image_index is not None else ClueType.ROUTINE_TEXT,
        value=SECRET_TEXT,
        region=None,
        confidence=0.9,
        source=ClueSource.VLM if image_index is not None else ClueSource.TEXT,
    )


def test_summarize_counts_only_image_indexed_clues_as_image_derived() -> None:
    posts = [_post("1", image=True), _post("2", image=False), _post("3", image=True)]
    extractions = [
        PostExtraction(
            post_id="threads:1", clues=[_clue("threads:1", 0), _clue("threads:1", None)]
        ),
        PostExtraction(post_id="threads:2", clues=[_clue("threads:2", None)]),
        PostExtraction(post_id="threads:3", clues=[], error="手がかりを取り出せませんでした"),
    ]
    assert summarize(posts, extractions) == Counts(
        posts=3, posts_with_image=2, clues=3, image_clues=1, text_clues=2, failed_posts=1
    )


def test_format_contains_numbers_only() -> None:
    line = format_counts("画像あり", Counts(3, 2, 3, 1, 2, 0))
    assert "画像由来 1" in line
    assert SECRET_TEXT not in line


def test_strip_images_removes_images_without_touching_originals() -> None:
    posts = [_post("1", image=True)]
    stripped = strip_images(posts)
    assert stripped[0].images == []
    assert posts[0].images != []


@pytest.mark.parametrize("value", ["0", "11", "x"])
def test_limit_is_small(value: str) -> None:
    with pytest.raises(SystemExit):
        threads_verify.main(["--limit", value])


def _patch(monkeypatch: pytest.MonkeyPatch, *, reachable: bool = True) -> list[bool]:
    seen_include_images: list[bool] = []

    class FakeExtractor(Extractor):
        image_enabled = True

        async def model_reachable(self, timeout_s: float) -> bool:
            return reachable

        async def extract_post(self, value: Post, images: list[bytes]) -> list[Clue]:
            clues = [_clue(value.post_id, None)]
            if images:
                clues.append(_clue(value.post_id, 0))
            return clues

    async def fake_fetch(token: str, limit: int, *, include_images: bool = False):  # type: ignore[no-untyped-def]
        seen_include_images.append(include_images)
        return "owner", [_post("1", image=True), _post("2", image=False)][:limit]

    async def fake_images(post: Post) -> list[bytes]:
        return [b"x" for _ in post.images]

    monkeypatch.setattr(
        threads_verify, "build_extractor", lambda **_: FakeExtractor.__new__(FakeExtractor)
    )
    monkeypatch.setattr(threads_verify, "fetch_own_posts", fake_fetch)
    monkeypatch.setattr(threads_verify, "fetch_threads_images", fake_images)
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", SECRET_TOKEN)
    return seen_include_images


def test_both_mode_prints_counts_only_and_fetches_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _patch(monkeypatch)
    with pytest.raises(SystemExit) as exit_info:
        threads_verify.main(["--limit", "2", "--mode", "both"])
    assert exit_info.value.code == 0
    out = capsys.readouterr()
    assert "[画像なし]" in out.out
    assert "画像由来 0" in out.out
    assert "[画像あり]" in out.out
    assert "画像由来 1" in out.out
    for secret in (SECRET_TEXT, SECRET_URL, SECRET_TOKEN, "threads:1"):
        assert secret not in out.out + out.err
    assert seen == [True]


def test_unreachable_model_exits_2_before_fetching_posts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _patch(monkeypatch, reachable=False)
    with pytest.raises(SystemExit) as exit_info:
        threads_verify.main([])
    assert exit_info.value.code == 2
    assert seen == []
    assert SECRET_TOKEN not in capsys.readouterr().err


def test_missing_token_fails_without_leaking(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        threads_verify.main([])
    assert exit_info.value.code == 1
    assert "THREADS_ACCESS_TOKEN" in capsys.readouterr().err
