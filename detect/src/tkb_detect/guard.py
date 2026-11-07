"""写真・本文の送り先をチームのサーバーに限るための確認（許可リスト方式）。

設定の誤りで第三者の AI サービスや内部ネットワークに送らないよう、送り先の URL を検査する。

- 送ってよいのは、許可リスト `MODEL_ALLOWED_HOST_SUFFIXES`（カンマ区切り）に書いたホストだけ。
  - ホスト名を書いたときは、そのホストとサブドメインを許可する（`proxy.runpod.net` なら
    `abc-8000.proxy.runpod.net` も可）
  - IP を書いたときは、その IP と完全に一致するときだけ許可する
    （VPC 内の GPU を `10.x.x.x` で呼ぶため）
- 許可リストが空のときは loopback（localhost、127.0.0.0/8、::1）だけを許可する（開発用）。
  既知の第三者 AI ホストを拒否する方式には戻らない
- リンクローカル（169.254.0.0/16・fe80::/10、クラウドのメタデータIPを含む）・マルチキャスト・
  予約・未指定(0.0.0.0) の IP と、既知の第三者 AI サービスは、許可リストに書いても常に拒否する

DNS の解決結果は見ない。許可リストにはチームが管理するホストだけを書くこと。
"""

import ipaddress
import os
from collections.abc import Sequence
from urllib.parse import urlparse

from tkb_detect.errors import ForbiddenEndpointError

# 許可リストに書いても拒否する、既知の第三者 AI サービスのホスト接尾辞
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

# 許可リストを設定する環境変数（カンマ区切りのホスト接尾辞または IP）
ALLOWLIST_ENV_VAR = "MODEL_ALLOWED_HOST_SUFFIXES"

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def _env_allowlist() -> list[str]:
    return os.environ.get(ALLOWLIST_ENV_VAR, "").split(",")


def _parse_ip(host: str) -> IpAddress | None:
    # urlparse はホストの [] を外すが、許可リストに [fd00::15] と書かれた場合のために外しておく
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _matches_suffix(host: str, suffixes: Sequence[str]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


# IPv4 を埋め込んで別の IPv4 に届き得る IPv6 の帯（NAT64、6to4）。チームのサーバーでは使わない
_IPV4_EMBEDDING_V6_NETS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
    ipaddress.ip_network("2002::/16"),
)


def _reject_special_ip(ip: IpAddress, host: str) -> None:
    """チームのサーバーになり得ない特別用途の IP なら拒否する。"""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped  # ::ffff:169.254.169.254 のような書き方も IPv4 として見る
        elif any(ip in net for net in _IPV4_EMBEDDING_V6_NETS):
            raise ForbiddenEndpointError(f"IPv4 を埋め込んだ IPv6 には送れません: {host}")
    if ip.is_loopback:
        return  # ::1 は IPv6 の予約済みの帯（::/8）にも入るので、先に除く
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ForbiddenEndpointError(f"内部・特別用途のアドレスには送れません: {host}")


def _is_loopback(host: str, ip: IpAddress | None) -> bool:
    return host == "localhost" or (ip is not None and ip.is_loopback)


def _is_allowed(host: str, ip: IpAddress | None, entries: Sequence[str]) -> bool:
    """許可リストに一致するか。IP は IP の項目と完全一致、ホスト名は接尾辞で比べる。"""
    if ip is not None:
        return ip in {_parse_ip(e) for e in entries}
    return _matches_suffix(host, [e for e in entries if _parse_ip(e) is None])


def ensure_team_endpoint(base_url: str, allowed_host_suffixes: Sequence[str] | None = None) -> str:
    """送り先として使ってよい URL なら、末尾の / を除いて返す。

    allowed_host_suffixes を渡すとそれを許可リストにする（空のリストなら、許可リストは空）。
    None のときは環境変数 MODEL_ALLOWED_HOST_SUFFIXES を読む。
    """
    if any(c.isspace() or not c.isprintable() for c in base_url):
        raise ForbiddenEndpointError("接続先の URL に空白や制御文字が入っています")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ForbiddenEndpointError("接続先の URL が設定されていないか、http(s) ではありません")
    try:
        _ = parsed.port  # 数字でないポートは ValueError
    except ValueError:
        raise ForbiddenEndpointError("接続先の URL のポートが正しくありません") from None

    host = _normalize_host(parsed.hostname)
    if "%" in host:
        # IPv6 のゾーン ID（fe80::1%25eth0）などは IP として判定できないので送らない
        raise ForbiddenEndpointError(f"接続先のホストに % が入っています: {host}")
    ip = _parse_ip(host)

    # 1. 特別用途の IP と既知の第三者 AI サービスは、許可リストによらず常に拒否
    if ip is not None:
        _reject_special_ip(ip, host)
    if _matches_suffix(host, THIRD_PARTY_AI_HOST_SUFFIXES):
        raise ForbiddenEndpointError(f"第三者の AI サービスには送れません: {host}")

    raw = allowed_host_suffixes if allowed_host_suffixes is not None else _env_allowlist()
    entries = [n for n in (_normalize_host(e) for e in raw) if n]

    # 2. 許可リストが空なら loopback だけ（開発用）
    if not entries:
        if _is_loopback(host, ip):
            return base_url.rstrip("/")
        raise ForbiddenEndpointError(
            f"許可リスト（{ALLOWLIST_ENV_VAR}）が空なので、localhost 以外には送れません: {host}"
        )

    # 3. 許可リストに一致するホストだけ
    if not _is_allowed(host, ip, entries):
        raise ForbiddenEndpointError(f"許可リストにないホストには送れません: {host}")
    return base_url.rstrip("/")
