import sqlite3
from pathlib import Path

import pytest

from tkb_api.config import Settings
from tkb_api.main import create_app
from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION


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


def test_compose_passes_repository_env_only_to_api() -> None:
    compose = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.yml"
    api_and_header, web_service = compose.read_text(encoding="utf-8").split("  web:", maxsplit=1)

    assert "path: ../.env" in api_and_header
    assert "../data/processed:/app/data/processed:ro" in api_and_header
    assert "path: ../.env" not in web_service
    assert "BRAVE_SEARCH_API_KEY" not in web_service
    assert "path: /run/tkb_2613/web-secrets.env" in web_service


def _touch_gazetteer_tables(directory: Path, filenames: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (directory / filename).touch()


def test_default_gazetteer_selects_complete_processed_or_national_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    processed = Path("data/processed")
    national = processed / "national"
    required = ("stations.parquet", "postal.parquet", "muni_mesh.parquet")

    assert Settings(_env_file=None).gazetteer_dir == processed

    _touch_gazetteer_tables(national, required)
    assert Settings(_env_file=None).gazetteer_dir == national

    _touch_gazetteer_tables(processed, ("stations.parquet",))
    assert Settings(_env_file=None).gazetteer_dir == national

    _touch_gazetteer_tables(processed, required)
    assert Settings(_env_file=None).gazetteer_dir == processed


def test_env_example_does_not_pin_gazetteer_directory() -> None:
    example = Path(__file__).resolve().parents[2] / ".env.example"
    active_assignments = [
        line
        for line in example.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("GAZETTEER_DIR=")
    ]

    assert active_assignments == []


def test_explicit_gazetteer_dir_overrides_autoselection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "custom-tables"
    monkeypatch.setenv("GAZETTEER_DIR", str(explicit))

    assert Settings(_env_file=None).gazetteer_dir == explicit


def test_commons_reference_lookup_requires_enabled_live_cap_and_compatible_index(
    tmp_path: Path,
) -> None:
    def is_available(directory: Path) -> bool:
        return Settings(
            _env_file=None,
            mock_mode=False,
            commons_reference_lookup_enabled=True,
            diagnose_daily_limit=3,
            gazetteer_dir=directory,
        ).commons_reference_lookup_available

    assert Settings(_env_file=None).commons_reference_lookup_available is False
    absent_dir = tmp_path / "absent"
    assert is_available(absent_dir) is False

    mismatch_dir = tmp_path / "mismatch"
    mismatch_dir.mkdir()
    place_index = mismatch_dir / "places.sqlite3"
    with sqlite3.connect(place_index) as db:
        db.execute("PRAGMA user_version = 999")
    assert is_available(mismatch_dir) is False

    compatible_dir = tmp_path / "compatible"
    compatible_dir.mkdir()
    with sqlite3.connect(compatible_dir / "places.sqlite3") as db:
        db.execute(f"PRAGMA user_version = {PLACE_INDEX_SCHEMA_VERSION}")
    assert is_available(compatible_dir) is True

    assert (
        Settings(
            _env_file=None,
            mock_mode=False,
            commons_reference_lookup_enabled=True,
            diagnose_daily_limit=0,
            gazetteer_dir=tmp_path,
        ).commons_reference_lookup_available
        is False
    )
    assert (
        Settings(
            _env_file=None,
            mock_mode=True,
            commons_reference_lookup_enabled=True,
            diagnose_daily_limit=3,
            gazetteer_dir=tmp_path,
        ).commons_reference_lookup_available
        is False
    )


def test_commons_feature_uses_same_national_places_index_resolution(tmp_path: Path) -> None:
    processed = tmp_path / "data" / "processed"
    national = processed / "national"
    national.mkdir(parents=True)

    def write_index(path: Path, version: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute(f"PRAGMA user_version = {version}")

    def is_available(directory: Path) -> bool:
        return Settings(
            _env_file=None,
            mock_mode=False,
            commons_reference_lookup_enabled=True,
            diagnose_daily_limit=3,
            gazetteer_dir=directory,
        ).commons_reference_lookup_available

    root_index = processed / "places.sqlite3"
    national_index = national / "places.sqlite3"
    write_index(root_index, PLACE_INDEX_SCHEMA_VERSION)
    assert is_available(national) is True

    write_index(national_index, PLACE_INDEX_SCHEMA_VERSION - 1)
    assert is_available(national) is False

    write_index(national_index, PLACE_INDEX_SCHEMA_VERSION)
    assert is_available(national) is True

    explicit_parent = tmp_path / "custom"
    explicit = explicit_parent / "tables"
    write_index(explicit_parent / "places.sqlite3", PLACE_INDEX_SCHEMA_VERSION)
    assert is_available(explicit) is False


@pytest.mark.parametrize("mock_mode", [True, False])
def test_gazetteer_dependency_uses_selected_directory_in_mock_and_live_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mock_mode: bool
) -> None:
    from tkb_api.routes.diagnose import get_gazetteer
    from tkb_engine.gazetteer import Gazetteer

    expected = tmp_path / "selected-gazetteer"
    monkeypatch.setattr(
        "tkb_api.routes.diagnose._cached_gazetteer",
        lambda directory: Gazetteer(places_path=directory),
    )
    settings = Settings(_env_file=None, mock_mode=mock_mode, gazetteer_dir=expected)

    assert get_gazetteer(settings).places_path == expected


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


def _aws_example_env(monkeypatch: pytest.MonkeyPatch, prefixes: tuple[str, ...]) -> None:
    env_file = Path(__file__).resolve().parents[2] / "infra" / "aws.env.example"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith(prefixes) and not line.startswith("#"):
            monkeypatch.setenv(key, value)


def test_aws_env_example_sets_the_public_origin_for_the_x_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 未設定だと http://localhost:3000 になり、/api/x の POST がすべて 403 になる
    _aws_example_env(monkeypatch, ("X_", "THREADS_", "COOKIE_SECURE"))

    settings = Settings(_env_file=None)

    assert settings.x_public_origin.startswith("https://")
    assert settings.x_callback_url == f"{settings.x_public_origin}/api/x/callback"
    assert settings.origin_warnings() == []


def test_production_warns_when_the_x_demo_origin_is_still_local() -> None:
    settings = Settings(
        _env_file=None, cookie_secure=True, x_mock_mode=True, threads_mock_mode=False
    )

    [warning] = settings.origin_warnings()
    assert "X_PUBLIC_ORIGIN" in warning


def test_production_warns_when_open_threads_has_a_local_origin() -> None:
    public = "https://d111.cloudfront.net"
    settings = Settings(
        _env_file=None, cookie_secure=True, x_public_origin=public, threads_mock_mode=True
    )

    [warning] = settings.origin_warnings()
    assert "THREADS_PUBLIC_ORIGIN" in warning


def test_no_origin_warning_locally_or_when_the_demos_are_closed() -> None:
    assert Settings(_env_file=None).origin_warnings() == []  # COOKIE_SECURE=0（手元）
    closed = Settings(
        _env_file=None, cookie_secure=True, x_mock_mode=False, threads_mock_mode=False
    )
    assert closed.origin_warnings() == []


def test_origin_warning_is_logged_at_startup_without_stopping(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(_env_file=None, cookie_secure=True, x_mock_mode=True, share_enabled=False)

    with caplog.at_level("WARNING", logger="tkb_api"):
        app = create_app(settings)

    assert any("X_PUBLIC_ORIGIN" in record.getMessage() for record in caplog.records)
    app.state.sessions.close()
