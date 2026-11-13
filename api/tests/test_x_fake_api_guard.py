"""偽の X API（E2E テスト専用）は、本番の設定からは使えない。"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tkb_api.config import Settings
from tkb_api.routes.x import _x_api

LOCAL: dict[str, Any] = {
    "x_public_origin": "http://localhost:3100",
    "cookie_secure": False,
    "x_fake_api_base_url": "http://127.0.0.1:4010",
}


def test_default_points_to_the_real_x_api() -> None:
    assert _x_api(Settings(_env_file=None)) == "https://api.x.com"


def test_fake_api_is_allowed_only_for_local_http_tests() -> None:
    assert _x_api(Settings(_env_file=None, **LOCAL)) == "http://127.0.0.1:4010"
    assert _x_api(
        Settings(_env_file=None, **{**LOCAL, "x_fake_api_base_url": "http://[::1]:4010/"})
    )


@pytest.mark.parametrize(
    "override",
    [
        {"x_fake_api_base_url": "https://127.0.0.1:4010"},
        {"x_fake_api_base_url": "http://fake-x.example:4010"},
        {"x_fake_api_base_url": "http://10.0.0.5:4010"},
        {"x_fake_api_base_url": "http://127.0.0.1.nip.io:4010"},
        {"x_fake_api_base_url": "http://127.0.0.1:4010/2"},
        {"cookie_secure": True},
        {"x_public_origin": "https://d2qyby5y8mc03f.cloudfront.net"},
        {"x_public_origin": "http://192.168.0.10:3000"},
    ],
)
def test_fake_api_is_refused_outside_local_tests(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="X_FAKE_API_BASE_URL"):
        Settings(_env_file=None, **{**LOCAL, **override})


def test_production_env_example_cannot_start_with_the_fake_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = Path(__file__).resolve().parents[2] / "infra" / "aws.env.example"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            monkeypatch.setenv(key, value)
    assert "X_FAKE_API_BASE_URL" not in env_file.read_text(encoding="utf-8")
    monkeypatch.setenv("X_FAKE_API_BASE_URL", "http://127.0.0.1:4010")
    monkeypatch.setenv("X_PUBLIC_ORIGIN", "http://localhost:3000")  # 公開オリジンを偽っても

    with pytest.raises(ValidationError, match="X_FAKE_API_BASE_URL"):
        Settings(_env_file=None)  # COOKIE_SECURE=1 なので起動できない
