from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # 既定はモック。外部に一切接続しない
    mock_mode: bool = True
    vlm_base_url: str = ""
    vlm_api_key: SecretStr = SecretStr("")
    vlm_model: str = ""
    ocr_base_url: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    # Bluesky のログイン先
    bsky_service: str = "https://bsky.social"
    # ログインのセッションをメモリに置く時間（分）
    session_ttl_minutes: int = 30
    # HTTPS で公開するときは 1 にする（Cookie を HTTPS だけで送る）
    cookie_secure: bool = False
    # 診断で読む自分の投稿の件数（新しい順）
    max_posts: int = Field(default=30, ge=1, le=100)
    # MOCK_MODE の診断で流す、架空のデモ用アカウントの投稿（起動した場所からの相対パス）
    demo_fixture_path: Path = Path("eval/fixtures/demo_observations.json")
    # MOCK_MODE の診断で、投稿を 1 件流すごとに待つ秒数（画面で 1 件ずつ増える様子を見せるため）
    mock_event_interval_seconds: float = 0.3


@lru_cache
def get_settings() -> Settings:
    return Settings()
