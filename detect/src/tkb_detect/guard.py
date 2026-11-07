"""写真・本文の送り先をチームのサーバーに限るための確認。

設定の誤りで第三者の AI サービスや内部ネットワークに送らないよう、送り先の URL を検査する。

- リンクローカル（169.254.0.0/16・fe80::/10、クラウドのメタデータIPを含む）・マルチキャスト・
  予約・未指定(0.0.0.0) の IP は、チームのサーバーになり得ないため常に拒否する。
  loopback（localhost）と社内LAN のプライベートIPは、開発や社内配置で使うため許可する。
- `MODEL_ALLOWED_HOST_SUFFIXES`（カンマ区切りのホスト接尾辞）を設定すると、許可リスト方式になり、
  列挙したホスト（とそのサブドメイン）だけを許可する。本番で「チームのサーバーだけ」を担保するために使う。
- 許可リストが未設定のときは、既知の第三者 AI ホストを拒否する拒否リスト方式にフォールバックする。
"""

import ipaddress
import os
from urllib.parse import urlparse

from tkb_detect.errors import ForbiddenEndpointError

# 許可リストが未設定のときに拒否する、既知の第三者 AI サービスのホスト接尾辞
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

# 許可リストを設定する環境変数（カンマ区切りのホスト接尾辞）
ALLOWLIST_ENV_VAR = "MODEL_ALLOWED_HOST_SUFFIXES"


def _env_allowlist() -> list[str]:
    raw = os.environ.get(ALLOWLIST_ENV_VAR, "")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _matches_suffix(host: str, suffixes: list[str] | tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _reject_special_ip(host: str) -> None:
    """host が IP で、チームのサーバーになり得ない特別用途の帯なら拒否する。

    loopback と社内LAN のプライベートIPは許可（開発・社内配置で使うため）。
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # ホスト名は IP 検査の対象外
    if ip.is_loopback:
        return
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ForbiddenEndpointError(f"内部・特別用途のアドレスには送れません: {host}")


def ensure_team_endpoint(base_url: str, allowed_host_suffixes: list[str] | None = None) -> str:
    """送り先として使ってよい URL なら、末尾の / を除いて返す。

    allowed_host_suffixes を渡すとそれを許可リストにする。None のときは
    環境変数 MODEL_ALLOWED_HOST_SUFFIXES を読む。どちらも空なら拒否リスト方式。
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ForbiddenEndpointError("接続先の URL が設定されていないか、http(s) ではありません")

    host = parsed.hostname.lower()

    # 1. リンクローカル/メタデータ/特別用途IPは、許可リストの有無によらず常に拒否
    _reject_special_ip(host)

    # 2. 許可リスト方式（設定時）：列挙した接尾辞だけ許可
    suffixes = allowed_host_suffixes if allowed_host_suffixes is not None else _env_allowlist()
    if suffixes:
        if not _matches_suffix(host, suffixes):
            raise ForbiddenEndpointError(f"許可リストにないホストには送れません: {host}")
        return base_url.rstrip("/")

    # 3. 拒否リスト方式（未設定時のフォールバック）：既知の第三者 AI を拒否
    if _matches_suffix(host, THIRD_PARTY_AI_HOST_SUFFIXES):
        raise ForbiddenEndpointError(f"第三者の AI サービスには送れません: {host}")

    return base_url.rstrip("/")
