"""写真の送り先をチームのサーバーに限るための確認。

設定の誤りで第三者の AI サービスに写真を送らないよう、既知のホストを拒否する。
"""

from urllib.parse import urlparse

from tkb_detect.errors import ForbiddenEndpointError

THIRD_PARTY_AI_HOST_SUFFIXES = (
    "openai.com",
    "openai.azure.com",
    "googleapis.com",
    "anthropic.com",
    "mistral.ai",
    "cohere.ai",
    "cohere.com",
    "groq.com",
    "together.xyz",
    "together.ai",
    "openrouter.ai",
    "deepseek.com",
    "x.ai",
)


def ensure_team_endpoint(base_url: str) -> str:
    """送り先として使ってよい URL なら、末尾の / を除いて返す。"""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ForbiddenEndpointError("接続先の URL が設定されていないか、http(s) ではありません")

    host = parsed.hostname.lower()
    if any(host == s or host.endswith("." + s) for s in THIRD_PARTY_AI_HOST_SUFFIXES):
        raise ForbiddenEndpointError(f"第三者の AI サービスには送れません: {host}")

    return base_url.rstrip("/")
