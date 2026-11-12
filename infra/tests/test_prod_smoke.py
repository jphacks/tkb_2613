"""infra/prod_smoke.py の判定を、本番につながずに確かめる。

判定関数は応答を作って直接、通信まわり（リダイレクトを追わない・タイムアウト）は手元の
http.server を相手に確かめる。"""

import importlib.util
import json
import socket
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "prod_smoke.py"
FIXTURE = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "demo_observations.json"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prod_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass が sys.modules から自分のモジュールを引くので、先に登録する
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke: Any = _load()

WAF_BODY = b"<HTML><HEAD><TITLE>403 ERROR</TITLE></HEAD><BODY>Request blocked.</BODY></HTML>"
DEMO = {
    "demo": True,
    "conclusions": [
        {"rule": "R1", "attribute": "station", "value": "根津駅", "confidence": 0.9},
        {
            "rule": "R5",
            "attribute": "home_district",
            "value": "文京区 弥生1・2丁目",
            "confidence": 0.9,
        },
    ],
}


def resp(status: int, body: bytes = b"", ctype: str = "", **headers: str) -> Any:
    hdrs = {k.lower().replace("_", "-"): v for k, v in headers.items()}
    if ctype:
        hdrs["content-type"] = ctype
    return smoke.Response(status, hdrs, body)


def as_json(data: object, status: int = 200) -> Any:
    return resp(status, json.dumps(data).encode(), "application/json")


# --- 引数 ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        (" http://localhost:3000 ", "http://localhost:3000"),
    ],
)
def test_normalize_origin_accepts_origins(raw: str, expected: str) -> None:
    assert smoke.normalize_origin(raw) == expected


@pytest.mark.parametrize(
    "raw", ["example.com", "ftp://example.com", "https://example.com/api", "https://e.com/?a=1"]
)
def test_normalize_origin_rejects_non_origins(raw: str) -> None:
    with pytest.raises(ValueError):
        smoke.normalize_origin(raw)


def test_main_exits_2_on_bad_origin() -> None:
    with pytest.raises(SystemExit) as exc:
        smoke.main(["https://example.com/path"])
    assert exc.value.code == 2


# --- 判定 ---


def test_top_needs_200_html() -> None:
    assert smoke.judge_top(resp(200, b"<html>", "text/html; charset=utf-8"))[0]
    assert not smoke.judge_top(resp(200, b"{}", "application/json"))[0]
    ok, detail = smoke.judge_top(resp(301, location="https://example.com/"))
    assert not ok
    assert "リダイレクト" in detail
    assert "https://example.com/" in detail


def test_features_requires_share_disabled_unless_allowed() -> None:
    on = as_json({"share_enabled": True, "auth_mode": "oauth"})
    off = as_json({"share_enabled": False, "auth_mode": "oauth"})
    assert smoke.judge_features(off, allow_share_enabled=False)[0]
    assert not smoke.judge_features(on, allow_share_enabled=False)[0]
    assert smoke.judge_features(on, allow_share_enabled=True)[0]
    # Next.js の 404 ページなど、api に届いていない応答
    assert not smoke.judge_features(resp(200, b"<html>", "text/html"), allow_share_enabled=True)[0]
    assert not smoke.judge_features(as_json({}, 502), allow_share_enabled=True)[0]


def test_demo_matches_attribute_and_value() -> None:
    ok, detail = smoke.judge_demo(as_json(DEMO), "station", "最寄り駅", "根津駅")
    assert ok
    assert detail == "最寄り駅：根津駅"
    assert smoke.judge_demo(
        as_json(DEMO), "home_district", "ゴミの収集地区", "文京区 弥生1・2丁目"
    )[0]


def test_demo_reports_wrong_or_missing_value() -> None:
    wrong = as_json({"conclusions": [{"attribute": "station", "value": "上野駅"}]})
    ok, detail = smoke.judge_demo(wrong, "station", "最寄り駅", "根津駅")
    assert not ok
    assert "上野駅" in detail
    # 値が同じでも項目が違えば数えない（表示名は attribute から引くため）
    other = as_json({"conclusions": [{"attribute": "line", "value": "根津駅"}]})
    assert not smoke.judge_demo(other, "station", "最寄り駅", "根津駅")[0]
    assert not smoke.judge_demo(as_json({"demo": True}), "station", "最寄り駅", "根津駅")[0]
    assert not smoke.judge_demo(as_json({}, 503), "station", "最寄り駅", "根津駅")[0]


def test_expected_labels_match_web_messages() -> None:
    messages = (Path(__file__).resolve().parents[2] / "web/src/lib/messages.ts").read_text("utf-8")
    for attribute, label, _ in smoke.EXPECTED_CONCLUSIONS:
        assert f'{attribute}: "{label}"' in messages


def test_expected_values_come_from_demo_fixture() -> None:
    # 値は推理の結果なので fixture に直接は出ないが、根拠の手がかりは fixture にある
    text = FIXTURE.read_text("utf-8")
    assert "根津" in text
    assert "弥生" in text


@pytest.mark.parametrize(
    ("response", "ok"),
    [
        (resp(403, WAF_BODY, "text/html", server="CloudFront"), True),
        # アプリまで届いた応答
        (as_json({"detail": "Method Not Allowed"}, 405), False),
        (as_json({"detail": "検出はまだ実装されていません"}, 501), False),
        (as_json({"clues": []}, 200), False),
        (as_json({"detail": "forbidden"}, 403), False),
        # Next.js の内部経路が自分で返す本文なしの 403（入口で止まっていない）
        (resp(403, b""), False),
        (resp(404, b"<html>", "text/html"), False),
        (resp(302, location="/"), False),
    ],
)
def test_blocked_requires_edge_403(response: Any, ok: bool) -> None:
    assert smoke.judge_blocked(response)[0] is ok


# --- まとめ ---


def fake_fetcher(table: dict[tuple[str, str], Any]) -> Any:
    calls: list[tuple[str, str]] = []

    def fetch(origin: str, method: str, path: str, **_: Any) -> Any:
        calls.append((method, path))
        result = table.get((method, path))
        if isinstance(result, Exception):
            raise result
        return result if result is not None else resp(403, WAF_BODY, "text/html")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def healthy_table() -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/"): resp(200, b"<html>", "text/html"),
        ("GET", "/api/features"): as_json({"share_enabled": False, "auth_mode": "oauth"}),
        ("GET", "/api/demo/diagnosis"): as_json(DEMO),
    }


def test_run_checks_all_ok_and_demo_fetched_once() -> None:
    fetch = fake_fetcher(healthy_table())
    results = smoke.run_checks(
        "https://e.test", timeout=1, allow_share_enabled=False, fetcher=fetch
    )
    assert all(r.ok for r in results), results
    assert fetch.calls.count(("GET", "/api/demo/diagnosis")) == 1
    for path in smoke.BLOCKED_PATHS:
        assert ("GET", path) in fetch.calls
        assert ("POST", path) in fetch.calls
    assert len(results) == 2 + len(smoke.EXPECTED_CONCLUSIONS) + 2 * len(smoke.BLOCKED_PATHS)


def test_run_checks_reports_connection_errors_per_check() -> None:
    table = healthy_table()
    table[("GET", "/")] = TimeoutError("timed out")
    table[("POST", "/api/detect")] = as_json({"detail": "x"}, 501)
    results = smoke.run_checks(
        "https://e.test", timeout=1, allow_share_enabled=False, fetcher=fake_fetcher(table)
    )
    failed = {r.name: r.detail for r in results if not r.ok}
    assert set(failed) == {"GET /", "POST /api/detect 遮断"}
    assert "TimeoutError" in failed["GET /"]


# --- 通信（手元の http.server） ---


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, **headers: str) -> None:
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(302, b"", Location="/elsewhere")
        elif self.path == "/api/features":
            self._send(200, b'{"share_enabled":false}', Content_Type="application/json")
        else:
            self._send(403, WAF_BODY, Content_Type="text/html", Server="CloudFront")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self._send(403, WAF_BODY + body, Content_Type="text/html")

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_fetch_does_not_follow_redirects(server: str) -> None:
    got = smoke.fetch(server, "GET", "/", timeout=5)
    assert got.status == 302
    assert got.header("Location") == "/elsewhere"


def test_fetch_returns_error_statuses_and_sends_post_body(server: str) -> None:
    got = smoke.fetch(server, "GET", "/__internal/oauth/delete", timeout=5)
    assert got.status == 403
    assert got.header("server") == "CloudFront"
    posted = smoke.fetch(
        server, "POST", "/api/detect", timeout=5, body=b"{}", content_type="application/json"
    )
    assert posted.status == 403
    assert posted.body.endswith(b"{}")


def test_main_against_local_server(server: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = smoke.main([server, "--timeout", "5"])
    out = capsys.readouterr().out
    assert code == 1
    assert "NG  GET /  302 リダイレクト（追わない）→ /elsewhere" in out
    assert "OK  GET /api/features" in out
    assert "OK  POST /api/detect 遮断" in out


def test_unreachable_origin_fails_without_raising() -> None:
    # 空いているポートを取ってから閉じ、すぐに接続を断られる相手にする
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    results = smoke.run_checks(f"http://127.0.0.1:{port}", timeout=2, allow_share_enabled=False)
    assert results
    assert not any(r.ok for r in results)
    assert all("通信できない" in r.detail for r in results)
