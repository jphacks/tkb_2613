# detect

OCR と画像を読む言語モデルの呼び出し。応答をそのまま返す（手がかりの形式への変換は Hack Day 当日）。

- `VlmClient`：vLLM（OpenAI 互換 `POST {VLM_BASE_URL}/chat/completions`）。画像は data URL で送る
- `OcrClient`：PP-OCRv5。PaddleX の OCR サービス形式（`POST {OCR_BASE_URL}/ocr`、`{"file": base64, "fileType": 1}`）を想定
- `mock_mode=True`（既定）のときは固定の値を返し、接続しない
- 接続先は `ensure_team_endpoint` で確認し、第三者の AI サービス（OpenAI、Gemini など）は拒否する
