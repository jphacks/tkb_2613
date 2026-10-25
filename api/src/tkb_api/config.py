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
    # MOCK_MODE の診断で、投稿・手がかりを 1 件流すごとに待つ秒数（診断中の画面の演出を見せるため。
    # デモの 10 件で約 16 秒。本番は待たない）
    mock_event_interval_seconds: float = 0.8
    # 推理ルールが引く data-prep の表（stations・postal・muni_mesh）。make data で作る。
    # 読めないときは、表を使うルール（R1 の最寄り駅など）だけを飛ばす
    gazetteer_dir: Path = Path("data/processed")
    # 診断の SSE で、イベントの間がこの秒数より空いたら keep-alive のコメントを送る
    # （Vercel は 120 秒、Cloudflare は 100 秒、何も届かないと接続を切るため）
    sse_keepalive_seconds: float = Field(default=15, gt=0)
    # Web での照合（2段目）。既定はオフ。検索はチームのサーバーで動かす SearXNG を通す
    web_lookup_enabled: bool = False
    search_base_url: str = "http://localhost:8888"
    # MOCK_MODE の照合で返す、架空の人物の固定結果
    demo_lookup_path: Path = Path("eval/fixtures/demo_web_lookup.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
