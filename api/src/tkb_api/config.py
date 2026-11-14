import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tkb_api.limits import PublicWindow
from tkb_common.place_names import PLACE_INDEX_SCHEMA_VERSION
from tkb_engine.gazetteer import resolve_places_index_path

# 偽の X API を許す手元のホスト
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
GAZETTEER_REQUIRED_FILES = ("stations.parquet", "postal.parquet", "muni_mesh.parquet")


def _has_complete_gazetteer(directory: Path) -> bool:
    return all((directory / filename).is_file() for filename in GAZETTEER_REQUIRED_FILES)


def _has_compatible_place_index(directory: Path) -> bool:
    """Require local POI and mesh indexes before advertising Commons lookup."""
    if not (directory / "muni_mesh.parquet").is_file():
        return False
    path = resolve_places_index_path(directory)
    if path is None:
        return False
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True) as db:
            row = db.execute("PRAGMA user_version").fetchone()
    except (OSError, sqlite3.Error, ValueError):
        return False
    return row is not None and row[0] == PLACE_INDEX_SCHEMA_VERSION


def _default_gazetteer_dir() -> Path:
    """Prefer complete legacy tables, then the national dataset, else legacy path."""
    processed = Path("data/processed")
    national = processed / "national"
    if _has_complete_gazetteer(processed):
        return processed
    if _has_complete_gazetteer(national):
        return national
    return processed


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # 既定はモック。外部に一切接続しない
    mock_mode: bool = True
    vlm_base_url: str = ""
    vlm_api_key: SecretStr = SecretStr("")
    vlm_model: str = ""
    text_backend: Literal["vlm", "ollama"] = "vlm"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b-instruct"
    ocr_base_url: str = ""
    # VLM と OCR の送り先の許可リスト（カンマ区切りのホスト名か IP）。
    # 空なら localhost だけに送れる。
    # .env からも読めるよう、ここで受けて build_extractor に渡す（detect/src/tkb_detect/guard.py）
    model_allowed_host_suffixes: str = ""
    # 公開Web検索の秘密鍵。明示的な診断同意がある場合のみ使用し、クライアントへ返さない。
    brave_search_api_key: SecretStr = SecretStr("")
    # Optional Commons geosearch and thumbnail comparison; off until explicitly enabled.
    commons_reference_lookup_enabled: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    # Bluesky のログイン先
    bsky_service: str = "https://bsky.social"
    auth_mode: Literal["oauth", "app_password"] = "app_password"
    internal_auth_secret: SecretStr = SecretStr("")
    oauth_web_origin: str = "http://127.0.0.1:3000"
    # ログインのセッションをメモリに置く時間（分）
    session_ttl_minutes: int = 30
    # HTTPS で公開するときは 1 にする（Cookie を HTTPS だけで送る）
    cookie_secure: bool = False
    # 診断で読む自分の投稿の件数（新しい順）
    max_posts: int = Field(default=30, ge=1, le=100)
    # MOCK_MODE の診断で流す、架空のデモ用アカウントの投稿（起動した場所からの相対パス）
    demo_fixture_path: Path = Path("eval/fixtures/demo_observations.json")
    # ローカル画像は明示的に有効化した開発環境だけで配信する（既定では無効）
    mock_local_assets_enabled: bool = False
    # MOCK_MODE の診断で、投稿・手がかりを 1 件流すごとに待つ秒数（診断中の画面の演出を見せるため。
    # デモの 10 件で約 16 秒。本番は待たない）
    mock_event_interval_seconds: float = 0.8
    # 推理ルールが引く data-prep の表（stations・postal・muni_mesh）。make data で作る。
    # 読めないときは、表を使うルール（R1 の最寄り駅など）だけを飛ばす
    gazetteer_dir: Path = Field(default_factory=_default_gazetteer_dir)
    # 診断の SSE で、イベントの間がこの秒数より空いたら keep-alive のコメントを送る
    # （Vercel は 120 秒、Cloudflare は 100 秒、何も届かないと接続を切るため）
    sse_keepalive_seconds: float = Field(default=15, gt=0)
    # 明示的に共有した診断結果の保存先と有効期間。アプリ再起動後も閲覧できるようファイルに置く。
    share_db_path: Path = Path("data/private/shared_results.sqlite3")
    share_ttl_minutes: int = Field(default=120, ge=1, le=1440)
    # 閲覧リンクの機能。0 なら保存先も作らず、閲覧リンクの API は 404（share_disabled）。
    # 公開中の本番では 0（docs/aws-migration.md の 14.1）。ローカルの既定はこれまでどおり 1
    share_enabled: bool = True

    # --- 乱用対策と公開時間帯（docs/aws-migration.md の 5章）。0 の上限は「制限しない」 ---
    # 1アカウント（DID）1日（日本時間）の診断回数
    diagnose_daily_limit: int = Field(default=3, ge=0)
    # 同時に診断できる数。空きがなければ待たずに 503 を返す
    max_concurrent_diagnoses: int = Field(default=2, ge=0)
    # 混雑で断るときに Retry-After で伝える秒数
    diagnose_busy_retry_after_seconds: int = Field(default=30, ge=1)
    # 診断の枠を返し損ねても、この秒数たてば空いたものとして扱う（診断の最長時間より長くする）
    diagnose_slot_timeout_seconds: float = Field(default=900, gt=0)
    # 公開する時間帯。JSON の配列 [{"start": "2026-11-16T20:00:00+09:00", "end": "…"}]。
    # 空なら制限しない（ローカル開発用）
    public_windows: list[PublicWindow] = []
    # 診断を始める前に、モデルのサーバーが応答するかを確かめる待ち時間（秒）
    model_probe_timeout_seconds: float = Field(default=3, gt=0)

    # X 専用。X の用途承認と有料 API の予算承認を得るまでは実接続しない。
    threads_app_id: str = ""
    threads_app_secret: SecretStr = SecretStr("")
    threads_callback_url: str = ""
    threads_public_origin: str = "http://localhost:3000"
    threads_enabled: bool = False
    threads_query_logs_redacted: bool = False
    threads_mock_mode: bool = True
    threads_gpu_demo_enabled: bool = False
    threads_max_posts: int = Field(default=30, ge=1, le=30)
    # Threads の本文を読むモデル。既定は Bluesky と同じ vLLM（VLM_*・MODEL_ALLOWED_HOST_SUFFIXES）。
    # ollama にすると OLLAMA_BASE_URL・OLLAMA_MODEL で読む。写真は読まない
    threads_text_backend: Literal["vlm", "ollama"] = "vlm"
    x_client_id: str = ""
    x_client_secret: SecretStr = SecretStr("")
    x_callback_url: str = "http://localhost:3000/api/x/callback"
    x_public_origin: str = "http://localhost:3000"
    x_use_case_approved: bool = False
    x_paid_reads_approved: bool = False
    x_query_logs_redacted: bool = False
    x_mock_mode: bool = True
    x_max_posts: int = Field(default=5, ge=1, le=30)
    # X API で1日（UTC）に読んでよいリソース数の上限。超えたら X を呼ばずに断る。
    # 既定は本人確認1件と投稿5件の2回分。0 なら実取得をすべて断る
    x_daily_resource_limit: int = Field(default=12, ge=0, le=10000)
    # X の結果の出し方。aggregate は地名・駅名などを値ごとに数える今の表示、
    # highlight は本文中の地名・駅名に色を付けるだけで、値ごとに数えない
    x_info_view: Literal["aggregate", "highlight"] = "aggregate"
    # E2E テスト専用：偽の X API の向き先（例 http://127.0.0.1:4010）。空なら本物の https://api.x.com。
    # 手元の http の loopback だけを許し、COOKIE_SECURE=1 や公開オリジンが loopback でない設定
    # （本番）では起動時に失敗させる（_fake_x_api_only_in_local_tests）
    x_fake_api_base_url: str = ""

    @model_validator(mode="after")
    def _fake_x_api_only_in_local_tests(self) -> Self:
        if not self.x_fake_api_base_url:
            return self
        fake = urlparse(self.x_fake_api_base_url)
        public = urlparse(self.x_public_origin)
        if (
            fake.scheme != "http"
            or fake.hostname not in LOOPBACK_HOSTS
            or fake.path not in ("", "/")
            or fake.query
            or self.cookie_secure
            or public.scheme != "http"
            or public.hostname not in LOOPBACK_HOSTS
        ):
            raise ValueError(
                "X_FAKE_API_BASE_URL は手元の E2E テスト専用です"
                "（http の loopback、COOKIE_SECURE=0）"
            )
        return self

    def origin_warnings(self) -> list[str]:
        """本番（COOKIE_SECURE=1）なのに、開けている X・Threads の公開オリジンが手元のままのとき。

        X_PUBLIC_ORIGIN・THREADS_PUBLIC_ORIGIN が未設定だと既定の http://localhost:3000 になり、
        /api/x・/api/threads の POST がすべて Origin の確認（check_origin）で 403 になる。
        起動は止めず、ログに出す警告の文だけを返す。
        """
        if not self.cookie_secure:
            return []
        warnings: list[str] = []
        if self.x_mock_mode and urlparse(self.x_public_origin).hostname in LOOPBACK_HOSTS:
            warnings.append(
                "X_MOCK_MODE=1 ですが X_PUBLIC_ORIGIN が手元のオリジンのままです。"
                "/x の合成デモの POST は 403 になります（公開の HTTPS オリジンを設定してください）"
            )
        threads_open = self.threads_mock_mode or self.threads_enabled
        if threads_open and urlparse(self.threads_public_origin).hostname in LOOPBACK_HOSTS:
            warnings.append(
                "Threads を開けていますが THREADS_PUBLIC_ORIGIN が手元のオリジンのままです。"
                "/threads の POST は 403 になります（公開の HTTPS オリジンを設定してください）"
            )
        return warnings

    @property
    def public_web_lookup_available(self) -> bool:
        """公開Web検索の同意欄を出せるか。

        モックは外へ通信せず固定の架空候補を返すので、デモで流れを見せられるよう常に真。
        実モードは BRAVE_SEARCH_API_KEY が空でないときだけ真。キーの値や長さは外へ出さない。
        """
        return self.mock_mode or bool(self.brave_search_api_key.get_secret_value().strip())

    @property
    def photo_place_web_lookup_available(self) -> bool:
        """Enable paid photo-place search only with a finite positive daily diagnosis cap."""
        return (
            not self.mock_mode
            and self.diagnose_daily_limit > 0
            and bool(self.brave_search_api_key.get_secret_value().strip())
        )

    @property
    def commons_reference_lookup_available(self) -> bool:
        """Require explicit live opt-in, a finite cap, and a compatible local POI index."""
        return (
            not self.mock_mode
            and self.diagnose_daily_limit > 0
            and self.commons_reference_lookup_enabled
            and _has_compatible_place_index(self.gazetteer_dir)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
