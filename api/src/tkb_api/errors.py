"""画面が理由ごとに文言を出し分けるエラー応答。

形は {"detail": {"code": "<理由>", "message": "<日本語>", ...}}。画面は code で文言を選び
（web/src/lib/messages.ts）、message は画面以外の呼び出し側とログのため。
code の一覧は docs/api-sse-contract.md に書く。
"""

from typing import Any

from fastapi import HTTPException


def refusal(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message, **extra}, headers=headers)


BLUESKY_BUSY_MESSAGE = "Bluesky が混雑しています。しばらくしてからもう一度お試しください"
