# Threads 診断 PoC（ローカル限定）

テスター本人のアクセストークンで `/me` と `/me/threads` を読み、本文付き投稿を最大30件、既存の `Post` 型に変換して抽出・推論パイプラインへ渡す。画像URLは現行の Bluesky CDN 制限に合わないため使わない。削除 API、OAuth、画面、公開 API は追加していない。診断中の `plan` はローカルでの仮除外計算であり、投稿は削除しない。

## 実行

Meta の Threads API テスター用アクセストークン（`threads_basic` 権限）と、既存のローカル VLM 設定（`VLM_BASE_URL`、`VLM_API_KEY`、`VLM_MODEL`、必要に応じ `MODEL_ALLOWED_HOST_SUFFIXES`）を用意する。トークンをシェル履歴に直接書かず、手元の安全な方法で `THREADS_ACCESS_TOKEN` をプロセスの環境変数に設定する。PoC はトークンを `.env` から自動読込しない。

```sh
uv run python -m tkb_api.threads_poc
```

出力は本人IDの確認結果と件数だけ。投稿本文、トークン、推定値は表示しない。抽出失敗があれば終了コード1。APIが拒否した場合も応答本文は表示しない。実APIへの接続は専用の本人テストアカウントでのみ行う。

Threads の現在の公式資料：[Meta の API コレクション](https://www.postman.com/meta/threads/collection/dht3nzz/threads-api)、[本人投稿の取得](https://www.postman.com/meta/threads/request/34203612-fea6c131-986c-4bf0-9908-fa38a77fa2d2)。

## 次の段階

OAuth を追加するなら、Threads アプリ固有の ID・secret、HTTPS コールバック、`state` 検証、短命の開始Cookie、トークン更新・失効、本人セッションと Bluesky セッションの分離、Threads 用の読み取り専用 UI・API、レート制限と運用テストが必要。Threads の削除操作を画面に出さないことも確認する。
