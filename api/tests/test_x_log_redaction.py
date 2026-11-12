"""X OAuth のコールバック（code・state）が FastAPI と uvicorn のログに残らないことを、
実際の uvicorn に偽のリクエストを送って確かめる。X には接続しない（respx で塞ぐ）。"""

import logging
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import uvicorn

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_api.routes import x as x_routes
from tkb_api.routes.x import XCallbackAccessFilter

CODE = "SyntheticCode4f2a"
STATE = "SyntheticState9c1d"
LIVE = {
    "x_mock_mode": False,
    "x_use_case_approved": True,
    "x_paid_reads_approved": True,
    "x_query_logs_redacted": True,
    "x_client_id": "synthetic-client",
    "x_client_secret": "synthetic-secret",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@contextmanager
def _serve(**settings: Any) -> Iterator[str]:
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    app = create_app(
        settings=Settings(
            _env_file=None,
            x_public_origin=origin,
            x_callback_url=f"{origin}/api/x/callback",
            gazetteer_dir=Path("/missing-x-gazetteer"),
            share_enabled=False,
            **settings,
        )
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=True)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn が起動しませんでした")
        time.sleep(0.05)
    try:
        yield origin
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def x_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.route(host="127.0.0.1").pass_through()
        yield router


def _assert_not_logged(caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]) -> None:
    # テスト側の httpx クライアントは送った URL を記録するので、サーバーのスレッドの記録だけを見る
    main = threading.main_thread().ident
    server_records = [record for record in caplog.records if record.thread != main]
    assert any(record.name == "uvicorn.access" for record in server_records)
    formatter = logging.Formatter("%(name)s %(message)s")
    texts = [formatter.format(record) for record in server_records]
    out, err = capfd.readouterr()
    for text in [*texts, out, err]:
        assert CODE not in text
        assert STATE not in text


def test_callback_query_is_not_logged_when_live_is_closed(
    caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str], x_mock: respx.MockRouter
) -> None:
    caplog.set_level(logging.DEBUG)
    paths = [
        f"/api/x/callback?code={CODE}&state={STATE}",
        f"/api/x/callback/?code={CODE}&state={STATE}",
        f"//api/x/callback?code={CODE}&state={STATE}",
        f"/api/x/%63allback?code={CODE}&state={STATE}",
    ]
    with (
        _serve() as origin,
        httpx.Client(base_url=origin, follow_redirects=False) as client,
    ):
        # httpx は "//api/..." をホスト名と解釈するので、生のパスとして送る
        statuses = [
            client.get(httpx.URL(origin).copy_with(raw_path=path.encode())).status_code
            for path in paths
        ]
    assert statuses[0] == 403
    _assert_not_logged(caplog, capfd)


def test_callback_query_is_not_logged_on_state_mismatch_and_x_failures(
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
    x_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    token = x_mock.post("https://api.x.com/2/oauth2/token")

    async def broken_user(_: str) -> tuple[str, str]:
        raise RuntimeError("synthetic unexpected failure")

    monkeypatch.setattr(x_routes, "get_my_user", broken_user)
    with (
        _serve(**LIVE) as origin,
        httpx.Client(base_url=origin, follow_redirects=False) as client,
    ):
        # state も start の Cookie もない
        mismatch = client.get(f"/api/x/callback?code={CODE}&state={STATE}")

        def callback_with_valid_state() -> httpx.Response:
            started = client.post(
                "/api/x/start", json={"consent": True}, headers={"Origin": origin}
            )
            state = httpx.URL(started.json()["authorize_url"]).params["state"]
            return client.get(f"/api/x/callback?code={CODE}&state={state}")

        token.respond(500)
        exchange_failed = callback_with_valid_state()
        token.respond(
            json={"access_token": "t", "token_type": "bearer", "scope": "tweet.read users.read"}
        )
        unexpected = callback_with_valid_state()
    assert mismatch.status_code == 400
    assert exchange_failed.status_code == 502
    assert unexpected.status_code == 500
    sent = [call.request for call in token.calls]
    assert sent and all(CODE in call.content.decode() for call in sent)  # code は X にだけ渡る
    _assert_not_logged(caplog, capfd)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"/api/x/callback?code={CODE}&state={STATE}", "/api/x/callback"),
        (f"/api/x/callback/?code={CODE}", "/api/x/callback/"),
        (f"//api/x/callback?state={STATE}", "//api/x/callback"),
        (f"/api/x/%63allback?code={CODE}", "/api/x/%63allback"),
        (f"/API/X/callback?code={CODE}", "/API/X/callback"),
        ("/api/threads/callback?code=keep", "/api/threads/callback?code=keep"),
        ("/api/xyz?code=keep", "/api/xyz?code=keep"),
    ],
)
def test_access_filter_drops_queries_under_api_x(path: str, expected: str) -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1", "GET", path, "1.1", 303),
        None,
    )
    assert XCallbackAccessFilter().filter(record)
    assert isinstance(record.args, tuple)
    assert record.args[2] == expected
