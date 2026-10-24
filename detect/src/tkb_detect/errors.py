class DetectError(Exception):
    """モデル呼び出しの失敗（接続できない、応答が想定外など）。"""


class ForbiddenEndpointError(DetectError):
    """チームのサーバー以外（第三者の AI サービスなど）に送ろうとした。"""


class OutputCutOffError(DetectError):
    """VLM の出力が max_tokens に達して途中で切れた。"""
