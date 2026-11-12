#!/usr/bin/env python3
"""ログインなしで本番の公開オリジンに問い合わせて、最低限の動作と遮断を確かめる。

    python3 infra/prod_smoke.py https://<配信ID>.cloudfront.net

Python の標準ライブラリだけで動く（uv がなくてもよい）。確かめること：

1. 画面のトップ `/` が 200 の HTML を返す
2. 画面経由の `/api/features` が 200 の JSON を返す（api の `/health` は `/api` の外なので
   画面経由では届かない。ログイン不要で軽い `/api/features` を生存確認に使う）。
   本番は閲覧リンクをオフにするので `share_enabled` が false であること
   （`--allow-share-enabled` で外す）
3. `/api/demo/diagnosis` の conclusions に「最寄り駅：根津駅」と
   「ゴミの収集地区：文京区 弥生1・2丁目」がある。
   画面の表示名は `web/src/lib/messages.ts` の ATTRIBUTE_LABELS で attribute から引くので、
   データ上は attribute=station / value=根津駅、
   attribute=home_district / value=文京区 弥生1・2丁目 を探す
4. `/__internal/*`（Next.js の内部経路）と `/api/detect` が入口で遮断される。
   遮断は WAF の block-internal・block-detect（infra/terraform/edge.tf）で、
   CloudFront が 403 を返す。
   判定は「403 で、本文が空でも JSON でもない」（WAF の 403 は CloudFront のエラーページの HTML。
   アプリの FastAPI の応答は JSON で、Next.js の内部経路が自分で返す 403 は本文なしなので、
   どちらも「入口で止まっていない」として失敗にする）。GET と POST の両方を試す

リダイレクトは追わない（3xx は失敗として Location を出す。http:// を渡すと CloudFront の
https への 301 で失敗するので https:// を渡す）。各チェックの成否を1行ずつ出し、
1つでも失敗すれば終了コード1（引数の誤りは2）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_BODY_BYTES = 2 * 1024 * 1024
USER_AGENT = "tkb-prod-smoke/1"

# (attribute, 表示名, 値)。表示名は web/src/lib/messages.ts の ATTRIBUTE_LABELS と同じ
EXPECTED_CONCLUSIONS: tuple[tuple[str, str, str], ...] = (
    ("station", "最寄り駅", "根津駅"),
    ("home_district", "ゴミの収集地区", "文京区 弥生1・2丁目"),
)

# 外から遮断されるべき経路。%5F%5Finternal は Next.js のフォルダー名どおりの表記
# （WAF は2回デコードして比べる）
BLOCKED_PATHS: tuple[str, ...] = (
    "/__internal/oauth/delete",
    "/__internal/oauth/drop",
    "/%5F%5Finternal/oauth/delete",
    "/api/detect",
)
BLOCKED_STATUS = 403


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


@dataclass(frozen=True)
class Result:
    ok: bool
    name: str
    detail: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """リダイレクトを追わず、3xx をそのまま応答として受け取る。"""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def normalize_origin(raw: str) -> str:
    """引数の URL を「scheme://host[:port]」に揃える。パス・クエリつきや http(s) 以外は拒否する。"""
    parsed = urllib.parse.urlsplit(raw.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("http:// か https:// で始まるオリジンを渡してください")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("パスやクエリのないオリジン（例 https://example.com）を渡してください")
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch(
    origin: str,
    method: str,
    path: str,
    *,
    timeout: float,
    body: bytes | None = None,
    content_type: str | None = None,
) -> Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(  # noqa: S310  scheme は normalize_origin で http(s) に限る
        origin + path, data=body, method=method, headers=headers
    )
    try:
        with _OPENER.open(request, timeout=timeout) as resp:
            return Response(resp.status, _lower(resp.headers.items()), resp.read(MAX_BODY_BYTES))
    except urllib.error.HTTPError as error:
        with error:
            return Response(error.code, _lower(error.headers.items()), error.read(MAX_BODY_BYTES))


def _lower(items: Sequence[tuple[str, str]]) -> dict[str, str]:
    return {key.lower(): value for key, value in items}


def _json(resp: Response) -> Any:
    try:
        return json.loads(resp.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _unexpected_status(resp: Response, expected: int) -> str | None:
    if resp.status == expected:
        return None
    if 300 <= resp.status < 400:
        location = resp.header("location") or "(Location なし)"
        return f"{resp.status} リダイレクト（追わない）→ {location}"
    return f"状態 {resp.status}（{expected} のはず）"


def judge_top(resp: Response) -> tuple[bool, str]:
    problem = _unexpected_status(resp, 200)
    if problem:
        return False, problem
    if "text/html" not in resp.header("content-type"):
        return False, f"HTML ではない（{resp.header('content-type') or 'Content-Type なし'}）"
    return True, "200 HTML"


def judge_features(resp: Response, *, allow_share_enabled: bool) -> tuple[bool, str]:
    problem = _unexpected_status(resp, 200)
    if problem:
        return False, problem
    data = _json(resp)
    if not isinstance(data, dict) or not isinstance(data.get("share_enabled"), bool):
        return False, "応答が {share_enabled, auth_mode} の JSON ではない（api に届いていない）"
    detail = f"200 share_enabled={data['share_enabled']} auth_mode={data.get('auth_mode')}"
    if data["share_enabled"] and not allow_share_enabled:
        return False, detail + "（本番は SHARE_ENABLED=0 のはず）"
    return True, detail


def judge_demo(resp: Response, attribute: str, label: str, value: str) -> tuple[bool, str]:
    problem = _unexpected_status(resp, 200)
    if problem:
        return False, problem
    data = _json(resp)
    conclusions = data.get("conclusions") if isinstance(data, dict) else None
    if not isinstance(conclusions, list):
        return False, "応答に conclusions の配列がない"
    found = [
        c.get("value")
        for c in conclusions
        if isinstance(c, dict) and c.get("attribute") == attribute
    ]
    if value in found:
        return True, f"{label}：{value}"
    if not found:
        return False, f"{label}（{attribute}）の推定がない（公開データの表が入っていない？）"
    return False, f"{label} が {' / '.join(map(str, found))}（{value} のはず）"


def judge_blocked(resp: Response) -> tuple[bool, str]:
    server = resp.header("server") or "-"
    if resp.status != BLOCKED_STATUS:
        return False, f"状態 {resp.status}（遮断なら {BLOCKED_STATUS}） server={server}"
    if _json(resp) is not None:
        return False, f"{resp.status} だが JSON が返った（アプリまで届いている） server={server}"
    if not resp.body.strip():
        return (
            False,
            f"本文なしの {resp.status}（アプリの応答。入口の WAF の遮断ではない） server={server}",
        )
    return True, f"{resp.status} server={server}"


def run_checks(
    origin: str,
    *,
    timeout: float,
    allow_share_enabled: bool,
    fetcher: Callable[..., Response] = fetch,
) -> list[Result]:
    results: list[Result] = []

    def check(
        name: str, call: Callable[[], Response], judge: Callable[[Response], tuple[bool, str]]
    ) -> None:
        try:
            ok, detail = judge(call())
        except (OSError, TimeoutError) as error:  # URLError・接続失敗・タイムアウト
            ok, detail = False, f"通信できない（{type(error).__name__}: {error}）"
        results.append(Result(ok, name, detail))

    check("GET /", lambda: fetcher(origin, "GET", "/", timeout=timeout), judge_top)
    check(
        "GET /api/features",
        lambda: fetcher(origin, "GET", "/api/features", timeout=timeout),
        lambda r: judge_features(r, allow_share_enabled=allow_share_enabled),
    )
    demo: list[Response] = []

    def demo_once() -> Response:
        if not demo:
            demo.append(fetcher(origin, "GET", "/api/demo/diagnosis", timeout=timeout))
        return demo[0]

    for attribute, label, value in EXPECTED_CONCLUSIONS:
        check(
            f"GET /api/demo/diagnosis {label}",
            demo_once,
            partial(judge_demo, attribute=attribute, label=label, value=value),
        )
    for path in BLOCKED_PATHS:
        check(
            f"GET {path} 遮断",
            partial(fetcher, origin, "GET", path, timeout=timeout),
            judge_blocked,
        )
        # 遮断されていなくても害のない中身（空の画像・空の JSON）だけを送る
        body, ctype = (b"", "image/png") if path == "/api/detect" else (b"{}", "application/json")
        check(
            f"POST {path} 遮断",
            partial(fetcher, origin, "POST", path, timeout=timeout, body=body, content_type=ctype),
            judge_blocked,
        )
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ログインなしで公開オリジンの動作と遮断を確かめる")
    parser.add_argument("origin", help="公開オリジン（例 https://example.cloudfront.net）")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="1回の通信のタイムアウト（秒）",
    )
    parser.add_argument(
        "--allow-share-enabled",
        action="store_true",
        help="share_enabled=true でも失敗にしない（手元の確認用）",
    )
    args = parser.parse_args(argv)
    try:
        origin = normalize_origin(args.origin)
    except ValueError as error:
        parser.error(str(error))
    results = run_checks(origin, timeout=args.timeout, allow_share_enabled=args.allow_share_enabled)
    for result in results:
        print(f"{'OK' if result.ok else 'NG'}  {result.name}  {result.detail}")
    failed = sum(not r.ok for r in results)
    print(f"{len(results) - failed}/{len(results)} 件 OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
