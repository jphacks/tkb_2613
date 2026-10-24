from functools import lru_cache

from pydantic import SecretStr
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
    session_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
