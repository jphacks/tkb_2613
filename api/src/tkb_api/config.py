from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tkb_api.limits import PublicWindow


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
    # MOCK_MODE の診断で、投稿・手がかりを 1 件流すごとに待つ秒数（診断中の画面の演出を見せるため。
    # デモの 10 件で約 16 秒。本番は待たない）
    mock_event_interval_seconds: float = 0.8
    # 推理ルールが引く data-prep の表（stations・postal・muni_mesh）。make data で作る。
    # 読めないときは、表を使うルール（R1 の最寄り駅など）だけを飛ばす
    gazetteer_dir: Path = Path("data/processed")
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
    x_client_id: str = ""
    x_client_secret: SecretStr = SecretStr("")
    x_callback_url: str = "http://localhost:3000/api/x/callback"
    x_public_origin: str = "http://localhost:3000"
    x_use_case_approved: bool = False
    x_paid_reads_approved: bool = False
    x_query_logs_redacted: bool = False
    x_mock_mode: bool = True
    # 架空のX投稿だけを既存VLMへ送る実験経路。実X投稿は常にOllama経路のまま。
    x_gpu_demo_enabled: bool = False
    x_max_posts: int = Field(default=30, ge=1, le=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
