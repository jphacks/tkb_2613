# ローカル Ollama 本文診断（検証用）

既定 `TEXT_BACKEND=vlm` は従来どおり。本文だけを Qwen3 に切り替えるには、API を動かすローカル環境で `TEXT_BACKEND=ollama`、`OLLAMA_BASE_URL=http://localhost:11434`、`OLLAMA_MODEL=qwen3:4b-instruct` を設定する。`MOCK_MODE=0` も必要。`VLM_BASE_URL` を空にすると写真の取得・抽出を行わず、本文のみを診断する。VLM を設定すれば写真は既存経路で処理する。本文のモデルが使えない場合は診断開始前に 503 を返し、既定のVLM経路への自動送信はしない。

WSL2 で API を動かす場合、Windows の Ollama が `localhost:11434` に届く構成ならそのまま使う。`curl --noproxy '*' http://localhost:11434/api/tags` で確認する。届かないときは Ollama を WSL 内で起動するか、Windows と WSL のローカル通信設定を確認する。Ollama を `0.0.0.0` にバインドしたり、ルーターでポートを公開したりしない。Docker 内の `localhost` はコンテナ自身を指すので、この設定を Compose にそのまま渡しても Windows の Ollama には届かない。

送り先の `ensure_team_endpoint` はそのまま使う。`MODEL_ALLOWED_HOST_SUFFIXES` に GPU ホストが入っている場合は `localhost` も明示する。Ollama クライアントは環境プロキシを使わず、投稿本文をログ・ディスクへ保存しない。画像・本文の両方がある投稿で画像抽出が失敗した場合は本文の手がかりを残す。Ollama が返した各 `quote` が投稿本文に、その `value` が引用内に連続した文字列として含まれることを確認する。`post_id` と `quote` を Clue に保持する。

架空投稿の比較は `eval/fixtures/ollama_text_gold.json` の正解を固定して、`uv run python eval/ollama_text_benchmark.py` で実施する。スクリプトは集計値のみ表示する。正解との一致は type と value の完全一致で、部分一致を認めないため、近い表現も誤抽出として数える。メモリ欄は `/api/ps` のモデル常駐サイズから VRAM 分を差し引いた値で、プロセス全体のピーク RAM ではない。

2026-11-10 の WSL2 → Windows Ollama CPU 測定（架空投稿12件、正解13件）：

| モデル | 正解 | 漏れ | 余計な抽出 | JSON構文成功 | 引用・型の検証通過 | 平均秒/投稿 | CPU常駐サイズ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen3:1.7b | 3 | 10 | 11 | 12/12 | 7/12 | 6.06 | 1.76 GiB |
| qwen3:4b-instruct | 9 | 4 | 6 | 12/12 | 11/12 | 6.99 | 2.97 GiB |

両モデルとも JSON 構文は成立したが、引用・型の検証で棄却された投稿がある。4Bでも余計な抽出が6件あり、公開版の既定経路への切り替えには精度改善と本人投稿での評価が必要。

本人投稿の確認は、既存 OAuth セッションのあるローカル Web から Bluesky 診断を実行する。削除ボタンは押さない。Threads PoC はローカルのプロセス環境に `THREADS_ACCESS_TOKEN` がある場合のみ `uv run python -m tkb_api.threads_poc` を実行する。PoC は投稿・手がかり・結論の件数だけを表示する。いずれもトークン・投稿本文をレポートへ転記しない。
