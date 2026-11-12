from pathlib import Path

import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app


def test_defaults_are_for_local_development() -> None:
    settings = Settings()
    assert settings.mock_mode is True
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.cookie_secure is False


def test_production_values_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # infra/aws.env.example の値（compose の env_file から環境変数として渡る）
    monkeypatch.setenv("MOCK_MODE", "0")
    monkeypatch.setenv("COOKIE_SECURE", "1")
    monkeypatch.setenv("CORS_ORIGINS", '["https://d111.cloudfront.net"]')
    monkeypatch.setenv("WEB_BIND", "127.0.0.1")  # compose だけが使う。api は読み飛ばす

    settings = Settings()

    assert settings.mock_mode is False
    assert settings.cookie_secure is True
    assert settings.cors_origins == ["https://d111.cloudfront.net"]


def test_tests_do_not_read_a_local_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 手元の .env（MOCK_MODE=0 など）にテストが左右されない（tests/conftest.py）
    (tmp_path / ".env").write_text("MOCK_MODE=0\nCOOKIE_SECURE=1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.mock_mode is True
    assert settings.cookie_secure is False


def test_session_ttl_minutes_sets_the_session_store_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # web の OAuth（web/src/lib/server/oauth.ts の oauthTtlSeconds）も同じ環境変数を読む
    monkeypatch.setenv("SESSION_TTL_MINUTES", "60")

    settings = Settings(share_enabled=False)
    app = create_app(settings)

    assert settings.session_ttl_minutes == 60
    assert app.state.sessions._ttl == 60 * 60
    app.state.sessions.close()


def test_aws_env_example_keeps_live_x_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from tkb_api.routes.x import _live_ready

    env_file = Path(__file__).resolve().parents[2] / "infra" / "aws.env.example"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith("X_") and not line.startswith("#"):
            monkeypatch.setenv(key, value)

    settings = Settings()

    assert settings.x_use_case_approved is False
    assert settings.x_paid_reads_approved is False
    assert settings.x_mock_mode is True
    assert _live_ready(settings) is False


def test_x_live_flags_default_to_off() -> None:
    from tkb_api.routes.x import _live_ready

    settings = Settings(_env_file=None)

    assert settings.x_use_case_approved is False
    assert settings.x_paid_reads_approved is False
    assert settings.x_query_logs_redacted is False
    assert settings.x_mock_mode is True
    assert _live_ready(settings) is False
