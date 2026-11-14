# 当日のトラブル対応表（Award Day・公開日）

- 作成：2026-11-13（main `6517888` 時点のコードと設定を読んで書いた）
- 対象：11/15 Award Day（公開 11:00〜16:20、GPU 10:15 起動・16:30 停止）と 11/16〜18 の夜の公開（[infra/terraform/README.md](../infra/terraform/README.md) の「GPU のスケジュール」）
- 出典は `ファイル:行`。**「未確認」と書いたものは、コードから確かめられない（AWS 上の実際の値・AWS の画面の文言など）**。当日の前に、できるものは確かめて消す
- 秘密の値（VLM のキー、`INTERNAL_AUTH_SECRET`、アクセスキー）はこの文書にもチャットにも貼らない。`terraform.tfstate*` の中身も貼らない
- **本番を変える操作（`terraform apply`、`.env` の変更、コンテナの再起動、GPU の起動）は、当日の判断者（末尾の表）が決めてから行う**。`terraform apply` は前の plan を確認し、apply のたびに state をリポジトリの外へコピーする（[infra/terraform/README.md](../infra/terraform/README.md):7, 95-102）

## まず見る場所（早見表）

| 画面・応答 | まず疑う | 最初の確認 | 節 |
|---|---|---|---|
| 「ただいま準備中です。しばらくしてからもう一度お試しください」 | GPU（vLLM / OCR）が止まっている・起動中・キー違い | アプリの EC2 から `curl -s -o /dev/null -w '%{http_code}' http://10.0.2.10:8000/v1/models`（401 なら vLLM は起動済み） | [1](#1-gpuvllm--ocr-の-ec2の停止) |
| 「サーバーでエラーが起きました（403）」、または CloudFront の 403 のページ | WAF（レート制限・全遮断・試験用 IP 制限） | CloudWatch の `AWS/WAFV2` の `BlockedRequests` をルールごとに見る | [2](#2-会場の-ip-が回数制限に当たる) |
| 「今日の診断は 3 回までです。…」「混雑しています…」「このアカウントの別の診断が進んでいます…」 | アプリ側の制限（WAF ではない） | HTTP ステータス（429 / 503 / 409）を開発者ツールで見る | [2](#2-会場の-ip-が回数制限に当たる) |
| 「Bluesky でのログインに失敗しました…」「Bluesky との接続を開始できませんでした」 | OAuth（`PUBLIC_URL`、client metadata、内部秘密、5分の期限） | `curl -s https://<配信ID>.cloudfront.net/oauth-client-metadata.json` | [3](#3-oauth-の失敗) |
| 「時間が切れました。もう一度ログインしてください」 | セッションの 30 分切れ（アクセスでは延びない） | ログインからの経過時間 | [4](#4-セッション切れ) |
| CloudFront の 502 / 504 のページ、画面が開かない | コンテナかアプリの EC2 が止まっている | SSM で入り `systemctl status tkb-app`、`docker compose ps` | [5](#5-コンテナの停止) |
| 何をしても直らない・発表の時間が迫っている | — | **ログイン不要の体験デモ `/demo` に切り替える**（GPU も Bluesky も使わない。[web/src/lib/messages.ts](../web/src/lib/messages.ts):73-77） | — |

共通の前提：

- 構成は CloudFront（＋WAF）→ VPC origin → アプリの EC2（web :3000 → api :8001）→ GPU の EC2（固定 IP `10.0.2.10`）。どちらの EC2 も SSH なし、SSM で入る（[infra/terraform/README.md](../infra/terraform/README.md):5, 14-15）
- SSM での入り方：`aws ssm start-session --target "$(terraform output -raw app_instance_id)"` → `sudo -i` → `cd /opt/tkb_2613`（[infra/terraform/README.md](../infra/terraform/README.md):125-129）。GPU は `gpu_instance_id`（[infra/terraform/outputs.tf](../infra/terraform/outputs.tf):18-21）
- api はアクセスログを出さない（`--no-access-log`、[api/Dockerfile](../api/Dockerfile):42）。CloudFront と WAF のログも保存しない（[infra/terraform/edge.tf](../infra/terraform/edge.tf):122, 125-126）。**WAF はサンプルも無効**（各ルールの `sampled_requests_enabled = false`、[infra/terraform/edge.tf](../infra/terraform/edge.tf):172 など）。そのため「どのリクエストが止まったか」は見えず、見えるのは CloudWatch の件数と、手元での再現だけ
- **アプリの再起動は、利用中の全員のログインと診断結果、1日の診断回数を消す**（どれもメモリだけに持つ。[api/src/tkb_api/limits.py](../api/src/tkb_api/limits.py):8-9、[api/src/tkb_api/bluesky.py](../api/src/tkb_api/bluesky.py):237-246、[web/src/lib/server/oauth.ts](../web/src/lib/server/oauth.ts):23-34）

---

## 1. GPU（vLLM / OCR の EC2）の停止

### 症状

| 画面 | HTTP | 出典 |
|---|---|---|
| 「診断する」を押すと「ただいま準備中です。しばらくしてからもう一度お試しください」 | `POST /api/diagnose` が 503、`{"detail":{"code":"model_unavailable","message":"診断モデルの準備ができていません"}}` | [api/src/tkb_api/routes/diagnose.py](../api/src/tkb_api/routes/diagnose.py):371-377、[web/src/lib/messages.ts](../web/src/lib/messages.ts):301 |
| 診断の途中で止まった場合：投稿ごとに「手がかりを探せませんでした（VLM に接続できませんでした: ConnectError）」など | SSE は続き、`clues` イベントの `error` に理由が入る | [detect/src/tkb_detect/vlm_client.py](../detect/src/tkb_detect/vlm_client.py):157-160、[detect/src/tkb_detect/batch.py](../detect/src/tkb_detect/batch.py):7, 91、[web/src/lib/messages.ts](../web/src/lib/messages.ts):157 |

- 「準備中」は、診断を始める前に `GET {VLM_BASE_URL}/models` が 2xx にならないときに出る（待ち時間 `MODEL_PROBE_TIMEOUT_SECONDS`、既定 3 秒）。GPU 停止・vLLM 起動中だけでなく、**VLM のキーの食い違い（401）**でも同じ表示になる（[detect/src/tkb_detect/vlm_client.py](../detect/src/tkb_detect/vlm_client.py):119-137、[api/src/tkb_api/config.py](../api/src/tkb_api/config.py):76）
- `OCR_BASE_URL` が設定されていると OCR も確かめ、**OCR だけ落ちていても「準備中」になる**（[detect/src/tkb_detect/extract.py](../detect/src/tkb_detect/extract.py):119-134）。OCR の `/health` が 5xx か接続不可なら不可（[detect/src/tkb_detect/ocr_client.py](../detect/src/tkb_detect/ocr_client.py):58-64）
- 「準備中」で断った分は1日の回数に数えない。途中で GPU が落ちた診断は、始まった時点で1回と数えられている（[api/src/tkb_api/routes/diagnose.py](../api/src/tkb_api/routes/diagnose.py):405-407）
- 予定どおりの停止：11/15 は **16:30 に GPU が止まる**（公開 16:20 まで）。16:30 をまたいだ診断は途中で失敗する（[infra/terraform/README.md](../infra/terraform/README.md):27）

### 確かめ方

1. **GPU の状態**（手元、内藤の認証情報）
   ```bash
   aws ec2 describe-instances --region us-east-1 --instance-ids "$(terraform output -raw gpu_instance_id)" \
     --query 'Reservations[].Instances[].State.Name' --output text   # running / stopped / pending
   ```
   AWS コンソール：EC2 → インスタンス → `tkb_2613-gpu`（タグ `Role=gpu`、[infra/terraform/compute.tf](../infra/terraform/compute.tf):83）の状態とステータスチェック
2. **スケジュールが動いたか**：EventBridge Scheduler のスケジュール名は `tkb_2613-gpu-start-<日付>` / `tkb_2613-gpu-stop-<日付>`（例 `tkb_2613-gpu-start-2026-11-15`、[infra/terraform/schedule.tf](../infra/terraform/schedule.tf):31-45）。コンソール：Amazon EventBridge → スケジューラ → スケジュール。`aws scheduler get-schedule --name tkb_2613-gpu-start-2026-11-15`
3. **予算で止められていないか**：実績 $80 で Budgets action が GPU を止め、スケジュールのロールに `tkb_2613-deny-gpu-start` を付ける。付いていると**スケジュールでも起動しない**（[infra/terraform/README.md](../infra/terraform/README.md):294, 301-308）
   ```bash
   aws iam list-attached-role-policies --role-name tkb_2613-gpu-scheduler
   ```
4. **vLLM が応答するか**（アプリの EC2 の中から）
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' http://10.0.2.10:8000/v1/models   # 401 なら起動済み（キーなしなので 401 が正常）
   curl -s -o /dev/null -w '%{http_code}\n' http://10.0.2.10:8080/health      # OCR を使う設定のときだけ
   grep -E '^(OCR_BASE_URL|VLM_BASE_URL|MODEL_ALLOWED_HOST_SUFFIXES)=' /opt/tkb_2613/.env
   ```
   接続できない（000）なら GPU 停止か vLLM 未起動。401 なのに画面が「準備中」なら、キーの食い違いか OCR を疑う（[infra/terraform/README.md](../infra/terraform/README.md):319）
5. **GPU の中**（SSM で GPU に入る）
   ```bash
   systemctl status tkb-vllm --no-pager
   docker logs --tail 50 vllm
   nvidia-smi
   systemctl status tkb-ocr --no-pager   # OCR を入れた場合だけ存在する
   ```
   vLLM は systemd の `tkb-vllm.service`、`Restart=on-failure`（[infra/terraform/templates/gpu-user-data.sh.tftpl](../infra/terraform/templates/gpu-user-data.sh.tftpl):22-45）

### 直し方

| 状況 | 直し方 | 所要時間 | 副作用・注意 |
|---|---|---|---|
| 予定外に止まっている（スケジュールの失敗・手で止めた） | `aws ec2 start-instances --region us-east-1 --instance-ids "$(terraform output -raw gpu_instance_id)"`（[infra/terraform/README.md](../infra/terraform/README.md):312-317） | 起動＋vLLM の読み込みで「数分」（README:319。当日の実測は未確認） | **予備担当（谷口）の IAM ユーザーは止めることしかできず、起動はできない**（[infra/terraform/iam.tf](../infra/terraform/iam.tf):56-85）。起動は内藤の認証情報で行う。手で起動した間は誰でも診断できる（README:32）。止め忘れに注意 |
| 起動が `InsufficientInstanceCapacity` で失敗する | すぐの回復手段はない。AZ を変えるには `gpu_availability_zone` を変えて `terraform apply`（GPU が作り直しになり、重み約 30GB を取り直す。README:70-76） | 長い（当日中は現実的でない見込み。未確認） | **apply は判断者の承認が要る**。発表は `/demo` に切り替える |
| vLLM のコンテナだけ落ちている | GPU の中で `systemctl restart tkb-vllm` | 数分（未確認） | 起動のたびに Secrets Manager からキーを読み直す（gpu-user-data.sh.tftpl:9-18） |
| OCR だけ落ちていて「準備中」になる | アプリの `.env` の `OCR_BASE_URL=` を空にして `systemctl restart tkb-app`（OCR なしで VLM だけで読む。[docs/setup.md](setup.md):213） | 再起動の時間（[5章](#5-コンテナの停止)） | 写真の該当箇所の枠が出なくなる。再起動で全員ログアウト。本番で OCR を動かしているかは未確認（`ocr_image` の既定は空、[infra/terraform/variables.tf](../infra/terraform/variables.tf):112-116） |
| キーの食い違い（`/v1/models` が 401 なのに「準備中」） | キーを入れ直したら、GPU とアプリの**両方**を起動し直す（`systemctl restart tkb-vllm`、`systemctl restart tkb-app`。README:106） | 数分 | アプリは全員ログアウト |
| 予算 $80 で止められた | Budgets のコンソールで action をリセットし、`tkb_2613-deny-gpu-start` を外す（README:301-308） | 数分 | **続けるかはチームで決める**（README:303）。費用が増える |
| 回復しない | 発表は `/demo`（架空アカウント、モデルにも Bluesky にもつながない）で見せる | 即時 | 実アカウントの診断は見せられない |

> RunPod に切り替える案（[docs/aws-migration.md](aws-migration.md) の 6.4）は `.env` の `VLM_BASE_URL` と `MODEL_ALLOWED_HOST_SUFFIXES` の変更とキーの差し替えが要り、送り先も変わる。Pod が今も動くかは未確認。当日に使うかは判断者が決める。

---

## 2. 会場の IP が回数制限に当たる

会場の Wi-Fi は1つのグローバル IP を大勢で共有していることが多い。制限は **WAF（IP ごと）** と **アプリ（アカウントごと・全体の同時数）** の2段で、症状が違う。

### 2-1. WAF のレート制限（IP ごと、5分）

| ルール名（メトリクス名も同じ） | 対象 | 上限（既定） | 出典 |
|---|---|---|---|
| `rate-login` | `POST` の `/api/session*` と `/auth/start` | `rate_limit_login` = **10 回 / 5分 / IP** | [infra/terraform/edge.tf](../infra/terraform/edge.tf):326-408、[infra/terraform/variables.tf](../infra/terraform/variables.tf):193-197 |
| `rate-diagnose` | `/api/diagnose*`・`/api/x/diagnose*`・`/api/threads/diagnose*`（メソッドを問わない） | `rate_limit_diagnose` = **10 回 / 5分 / IP** | edge.tf:410-457、variables.tf:199-203 |
| `rate-all` | `/_next/static/` 以外のすべて | `rate_limit_all` = **600 回 / 5分 / IP** | edge.tf:459-496、variables.tf:187-191 |

ほかに止めるルール：`kill-switch`（全遮断の IP セット `tkb_2613-block-all`、優先度 0）、`ip-reputation`（AWS の IP 評判リスト）、`block-detect`（`/api/detect`）、`block-internal`（`/__internal`）、`oauth-test-team-only`（`oauth_test_ipv4_cidrs` が空でないときだけ作られ、チーム IP 以外を全部止める）（edge.tf:128-324）。

- 実際に AWS に入っている値が既定のままかは未確認（`terraform.tfvars` で上書きできる）
- **会場で効きやすいのは `rate-diagnose`**：同じ IP から 5 分に 10 回で、審査員や来場者が同時に試すとすぐ届く。X・Threads の診断も同じ枠で数える（edge.tf:421）
- `rate-login` は OAuth のログイン開始（`/auth/start`）も数える（edge.tf:363-383）

**症状**

- WAF の遮断は `custom_response` を設定していないので、既定の **403** になる（edge.tf の各 `action { block {} }`）。429 は返さない
- 画面の中の API 呼び出し（ログイン・診断など）が止められると、本文が JSON でないので「**サーバーでエラーが起きました（403）**」になる（[web/src/lib/api.ts](../web/src/lib/api.ts):105-109、[web/src/lib/messages.ts](../web/src/lib/messages.ts):288）
- OAuth の開始が止められると「Bluesky との接続を開始できませんでした」（[web/src/components/login/LoginPanel.tsx](../web/src/components/login/LoginPanel.tsx):65-72）
- `rate-all`・全遮断などでページそのものが止められると、CloudFront の 403 のエラーページ（文言は AWS 側のもので未確認）
- `/api/features` が止められると、画面は `auth_mode` を読めず**アプリパスワードの入力欄を出す**（OAuth の本番でも）。そのまま送ると api は 404 を返し「サーバーでエラーが起きました（404）」になる（[web/src/lib/api.ts](../web/src/lib/api.ts):245-260、[web/src/components/login/LoginPanel.tsx](../web/src/components/login/LoginPanel.tsx):43-45、[api/src/tkb_api/routes/session.py](../api/src/tkb_api/routes/session.py):65-66）

**確かめ方**

- 手元（会場の回線）で：`curl -s -o /dev/null -w '%{http_code}\n' https://<配信ID>.cloudfront.net/api/features` が 403 なら、この IP が WAF に止められている。スマホのテザリングなど別の回線で 200 なら会場の IP の問題
- CloudWatch：名前空間 `AWS/WAFV2`、メトリクス `BlockedRequests`（と `AllowedRequests`）、ディメンション `WebACL=tkb_2613`、`Rule=rate-login` / `rate-diagnose` / `rate-all` / `kill-switch` / `oauth-test-team-only` / `ip-reputation`（メトリクス名は edge.tf の `metric_name`。CloudFront 用の WAF のメトリクスは us-east-1 で見る。ディメンションに `Region` が付くかは未確認）。コンソール：WAF & Shield → Web ACLs（Global (CloudFront)）→ `tkb_2613` → Traffic overview でも見られる
- いま止められている IP の一覧（内藤の認証情報。予備担当の IAM ユーザーには権限がない）：
  ```bash
  aws wafv2 get-rate-based-statement-managed-keys --scope CLOUDFRONT --region us-east-1 \
    --web-acl-name tkb_2613 --web-acl-id <Web ACL の ID> --rule-name rate-diagnose
  ```
  Web ACL の ID は `aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1` で探す
- 全遮断が入っていないか：IP セット `tkb_2613-block-all` が空であること（[infra/terraform/README.md](../infra/terraform/README.md):259-270）
- 試験用 IP 制限が残っていないか：Web ACL のルール一覧に `oauth-test-team-only` がないこと（README:240 で試験後に `[]` に戻す手順。戻したかは未確認）

**直し方**

| 手段 | 所要時間 | 副作用・注意 |
|---|---|---|
| 待つ | 5 分の窓で数えるので、回数が下がれば外れる（外れるまでの正確な時間は AWS の仕様で、数分の遅れがありうる。未確認） | 発表の進行が止まる |
| 発表者の端末をテザリングなど別の回線に切り替える | 即時 | 審査員の端末は会場の回線のまま |
| 発表は `/demo` で見せる | 即時 | `/demo` の読み込みも `rate-all` には数えられる |
| 上限を上げる：`terraform.tfvars` に `rate_limit_diagnose` などを書き、`terraform plan` → `apply` | plan・apply で数分（未確認） | **本番の変更。判断者の承認が要る**。apply 後は state をコピー。下限は 10（variables.tf:194, 200） |
| 試験用 IP 制限が残っていた：`oauth_test_ipv4_cidrs = []` にして plan → apply（README:240） | 数分 | 同上。残っていると**チーム以外が全員 403** なので最優先 |
| 全遮断を解除：同じ手順で `--addresses '[]'`（README:259-270） | 約 1 分 | 全遮断を入れた理由が解決しているか、判断者が確かめてから |

コンソールで WAF のルールを手で書き換えると、次の `terraform apply` で戻る（例外は全遮断の IP セットだけで、`ignore_changes` で手の変更を残す。edge.tf:137-139）。

### 2-2. アプリ側の制限（アカウントごと・全体）

| 制限 | 設定（本番の見本の値） | HTTP・コード | 画面の文言 | 出典 |
|---|---|---|---|---|
| 1 アカウント（DID）1 日（日本時間）の診断回数 | `DIAGNOSE_DAILY_LIMIT=0`（2026-11-14 から制限なし。正の値にすると有効） | 429 `daily_limit`、`Retry-After` は翌 0:00 まで | 「今日の診断は 3 回までです。明日の 0:00（日本時間）からまた診断できます」 | [api/src/tkb_api/routes/diagnose.py](../api/src/tkb_api/routes/diagnose.py):350-359、[web/src/lib/messages.ts](../web/src/lib/messages.ts):295-296、[infra/aws.env.example](../infra/aws.env.example):44 |
| 全体の同時診断数 | `MAX_CONCURRENT_DIAGNOSES=0`（2026-11-14 から制限なし） | 503 `busy`、`Retry-After: 30` | 「混雑しています。しばらくしてからもう一度お試しください」 | diagnose.py:360-368、messages.ts:297、aws.env.example:45-46 |
| 同じアカウントの同時診断 | 1（固定） | 409 `already_running` | 「このアカウントの別の診断が進んでいます。終わってからもう一度お試しください」 | diagnose.py:346-349、[api/src/tkb_api/limits.py](../api/src/tkb_api/limits.py):146-151、messages.ts:298 |
| 枠の返し損ね | `DIAGNOSE_SLOT_TIMEOUT_SECONDS=900` | — | 最後の動きから 900 秒で空いたとみなす | limits.py:112-117、aws.env.example:47 |
| Bluesky 側の回数制限 | — | 503 `bluesky_busy` | 「Bluesky が混雑しています。しばらくしてからもう一度お試しください」 | diagnose.py:287-290、[api/src/tkb_api/errors.py](../api/src/tkb_api/errors.py):24 |

- アプリの制限は **IP ではなくアカウント**（DID）で数える。会場の IP とは関係ない
- 2026-11-14 から1日の回数制限はない（`DIAGNOSE_DAILY_LIMIT=0`）。正の値に戻した場合は、ログインし直しても回数は戻らないので、リハーサルで使い切らないこと。同じセッションで画面を開き直したときは `GET /api/diagnosis` で前の結果を戻せるので、回数を使わない（diagnose.py:297-310）
- 本番の `.env` の実際の値は未確認（見本は aws.env.example）

**確かめ方**：ブラウザの開発者ツールのネットワークで `POST /api/diagnose` のステータスと応答の `detail.code` を見る。403 なら WAF、429 / 503 / 409 で JSON の `code` があればアプリ。

**直し方**

| 状況 | 直し方 | 副作用・注意 |
|---|---|---|
| デモアカウントが 1 日の上限 | (a) api を再起動すると回数が消える：アプリの EC2 で `docker restart tkb_2613-api-1`。(b) `.env` の `DIAGNOSE_DAILY_LIMIT` を上げて（0 は無制限）`systemctl restart tkb-app` | どちらも**全員の api のログインと診断結果が消える**（limits.py:8）。(b) は本番の設定変更なので判断者の承認が要る。0 にすると乱用対策がなくなる |
| 混雑（busy） | 30 秒待つ。前の診断が終わるか切れれば空く | 上限を上げると GPU が詰まる（vLLM は `--max-num-seqs 8`、gpu-user-data.sh.tftpl:37） |
| already_running | 前の診断のタブを閉じる。返し損ねでも最大 900 秒で空く | — |

---

## 3. OAuth の失敗

### 仕組み（どこで何が起きるか）

- 方式は `AUTH_MODE`（`oauth` / `app_password`）。api は `.env` から、web も同じ `.env` を `env_file` で読む（[api/src/tkb_api/config.py](../api/src/tkb_api/config.py):36、[web/src/lib/server/oauth.ts](../web/src/lib/server/oauth.ts):36-38、[infra/docker-compose.yml](../infra/docker-compose.yml):58-62）。本番の見本は `oauth`（[infra/aws.env.example](../infra/aws.env.example):36）。**11/12 21:00 の採用判定の結果、本番がどちらになったかは未確認**（README:240）
- 流れ：画面 → `POST /auth/start`（web）→ Bluesky の認可画面 → `GET /auth/callback`（web）→ web が api の `/__internal/oauth/complete` を `X-Internal-Auth` 付きで呼ぶ → api がセッションを作り `tkb_session` Cookie を返す（[web/src/app/auth/start/route.ts](../web/src/app/auth/start/route.ts)、[web/src/app/auth/callback/route.ts](../web/src/app/auth/callback/route.ts)、[api/src/tkb_api/routes/oauth_internal.py](../api/src/tkb_api/routes/oauth_internal.py):33-57）
- client metadata は `https://<PUBLIC_URL>/oauth-client-metadata.json`。`client_id` と `redirect_uris`（`<PUBLIC_URL>/auth/callback`）は `PUBLIC_URL` から作る（oauth.ts:53-72、[web/src/app/oauth-client-metadata.json/route.ts](../web/src/app/oauth-client-metadata.json/route.ts)）
- `PUBLIC_URL` は https でなければ例外（127.0.0.1 を除く）（oauth.ts:40-47）
- 認可の state は web のメモリに **5 分**、開始の Cookie `tkb_oauth_start` も 300 秒（oauth.ts:87、start/route.ts:20-22）
- 内部秘密 `INTERNAL_AUTH_SECRET` は `tkb-app-start` が起動のたびに作り、`/run/tkb_2613/api-secrets.env` と `web-secrets.env` で両方に渡す（[infra/tkb-app-start.sh](../infra/tkb-app-start.sh):10-15）

### 症状

| 画面 | 原因の候補 | 出典 |
|---|---|---|
| 「Bluesky との接続を開始できませんでした」（ログイン画面のまま） | `/auth/start` が 502（Bluesky のハンドル解決・認可サーバーへの接続失敗、`PUBLIC_URL` が不正）、400（ハンドルの形）、404（`AUTH_MODE` が oauth でない）、WAF の 403 | start/route.ts:6-26、LoginPanel.tsx:57-73 |
| Bluesky から戻ると「Bluesky でのログインに失敗しました。もう一度お試しください」（`/?auth_error=1`） | state が一致しない・5 分を過ぎた・web が途中で再起動した、Bluesky のトークン交換の失敗、内部秘密がない・食い違う（api が 403）、`AUTH_MODE` が oauth でない | callback/route.ts:6-43、oauth.ts:167-173、oauth_internal.py:24-30、messages.ts:97 |
| Bluesky の認可画面がエラーになる（文言は Bluesky 側。未確認） | Bluesky が client metadata を取れない（`PUBLIC_URL` と配信のドメインの食い違い、metadata が 200 にならない） | oauth.ts:53-72 |
| パスワード欄が出る（OAuth のはずなのに） | `/api/features` が読めず `app_password` 扱い（api の停止、WAF） | [web/src/lib/api.ts](../web/src/lib/api.ts):245-260、LoginPanel.tsx:43-45 |
| ログインはできたが「Bluesky から消す」で「N 件は消せませんでした。…」 | web の OAuth のトークンがない（web だけ再起動した、30 分を過ぎた）。web の `/__internal/oauth/delete` が 502 を返し、api は消せなかった件として数える | [web/src/app/%5F%5Finternal/oauth/delete/route.ts](../web/src/app/%5F%5Finternal/oauth/delete/route.ts):14-23、[api/src/tkb_api/routes/delete.py](../api/src/tkb_api/routes/delete.py):59-80、messages.ts:268 |

### 確かめ方

```bash
# 手元から。HTTPS 200・JSON・client_id と redirect_uris が今の配信のドメインになっていること
curl -s -D - https://<配信ID>.cloudfront.net/oauth-client-metadata.json
# 本番が今どちらの方式か
curl -s https://<配信ID>.cloudfront.net/api/features    # {"share_enabled":false,"auth_mode":"oauth"} など
```

アプリの EC2 で：

```bash
grep -E '^(AUTH_MODE|PUBLIC_URL|OAUTH_WEB_ORIGIN|CORS_ORIGINS|COOKIE_SECURE)=' /opt/tkb_2613/.env
ls -l /run/tkb_2613/ 2>/dev/null    # 起動後は消える（tkb-app-start.sh:11 の trap）。ないのが正常
docker logs --tail 100 tkb_2613-web-1
docker logs --tail 100 tkb_2613-api-1
```

- `PUBLIC_URL` と `CORS_ORIGINS` が `https://<配信ID>.cloudfront.net`（末尾の `/` なし）、`OAUTH_WEB_ORIGIN=http://web:3000` であること（[infra/aws.env.example](../infra/aws.env.example):34-39、[infra/terraform/README.md](../infra/terraform/README.md):138-139）
- web の callback は失敗の理由をログにも画面にも出さない（`catch` で `auth_error` に戻すだけ。callback/route.ts:40-43）。理由の切り分けは、上の設定の確認と、専用の架空アカウントで再現して行う
- 誰かが `docker compose up` を手で打つと、秘密のファイルがない状態でコンテナが作り直され、内部秘密が空になる。そうなると OAuth の完了が 403 で失敗する（README:144 の注意と同じ理由）

### 直し方

| 状況 | 直し方 | 所要時間 | 副作用・注意 |
|---|---|---|---|
| 一時的な失敗（5 分超え、Bluesky 側の一時エラー） | もう一度ログインしてもらう | 即時 | — |
| 内部秘密の食い違い・手で `docker compose up` した | `systemctl restart tkb-app` | 再起動の時間（5章） | 全員ログアウト |
| `PUBLIC_URL` などの設定ミス | `.env` を直して `systemctl restart tkb-app` | 同上 | 本番の設定変更。判断者の承認が要る |
| OAuth が直らない → **アプリパスワードに切り戻す** | `.env` の `AUTH_MODE=app_password` にして `systemctl restart tkb-app`（README:240） | 同上 | **README:240 で「11/13 の機能凍結後は認証方式を変えない」と決めている**ので、当日の切り替えは判断者が決める。全員ログアウト。画面はパスワード欄になり、利用者にアプリパスワードを作ってもらう必要がある。ログインは WAF の `rate-login`（10 回 / 5 分 / IP）に数えられる |
| 発表を止めたくない | `/demo` で見せる | 即時 | — |

---

## 4. セッション切れ

### 仕組み

| 持ち主 | 何を | 期限 | 出典 |
|---|---|---|---|
| api（メモリ） | アプリのセッション（`tkb_session` → ハンドル・DID）と最後の診断結果 | `SESSION_TTL_MINUTES`（既定 30 分）。**ログイン時から数え、アクセスでは延びない** | [api/src/tkb_api/bluesky.py](../api/src/tkb_api/bluesky.py):248-277、[api/src/tkb_api/config.py](../api/src/tkb_api/config.py):40、[infra/aws.env.example](../infra/aws.env.example):34-35 |
| ブラウザ | Cookie `tkb_session`（HttpOnly、SameSite=Lax、本番は Secure） | 同じ秒数の `max_age` | [api/src/tkb_api/routes/session.py](../api/src/tkb_api/routes/session.py):89-97、[api/src/tkb_api/routes/oauth_internal.py](../api/src/tkb_api/routes/oauth_internal.py):48-56 |
| web（Next.js のメモリ） | OAuth のトークン（削除に使う） | 同じ `SESSION_TTL_MINUTES`。callback の時点から数え、期限でトークンを失効させる | [web/src/lib/server/oauth.ts](../web/src/lib/server/oauth.ts):15-20, 141-156 |
| web（メモリ） | 認可途中の state | 5 分 | oauth.ts:87 |

### 症状

- 診断・仮除外・削除の途中で api が 401 を返すと、画面はログイン画面に戻り「**時間が切れました。もう一度ログインしてください**」を出す（[web/src/components/session/SessionProvider.tsx](../web/src/components/session/SessionProvider.tsx):58-60、[web/src/components/login/LoginPanel.tsx](../web/src/components/login/LoginPanel.tsx):120-124、[web/src/lib/messages.ts](../web/src/lib/messages.ts):99）
- ページを開き直したときに切れていた場合は、`GET /api/session` が 401 で、何も言わずにログイン画面になる（[web/src/lib/api.ts](../web/src/lib/api.ts):204、SessionProvider.tsx:34-42）
- 診断の SSE は始めたときだけセッションを確かめる。診断中に 30 分を過ぎると、結果は画面に出るがセッションのメモリには残らず、そのあとの「消したらどうなる」「Bluesky から消す」で 401 → 上の「時間が切れました」（[api/src/tkb_api/bluesky.py](../api/src/tkb_api/bluesky.py):283-291）
- OAuth では、web のトークンが先に消えると（web だけ再起動した場合など）、ログインは続いているのに削除だけが「N 件は消せませんでした」になる（3章の表）
- api の再起動ではセッションが全部消え、全員が 401 → 「時間が切れました」

### 確かめ方

- 開発者ツールで `/api/session` が 401 か、`/api/simulate`・`/api/delete`・`/api/diagnose` が 401 か
- ログインした時刻から 30 分たっているか。api・web のコンテナの起動時刻（`docker ps --format '{{.Names}} {{.Status}}'`）がログインより後なら、再起動で消えた
- 本番の `SESSION_TTL_MINUTES` の値（`grep SESSION_TTL_MINUTES /opt/tkb_2613/.env`。実際の値は未確認）

### 直し方

- 利用者にはもう一度ログインしてもらう（すぐ直る。1 日の診断回数は残るので、回数が残っているかに注意。2-2）
- **発表の直前にログインし直す**（30 分は延びないので、リハーサルでログインしたままだと本番中に切れる）
- 期限を延ばすには `.env` の `SESSION_TTL_MINUTES` を変えて `systemctl restart tkb-app`。全員ログアウトになり、本番の設定変更なので判断者の承認が要る。プライバシーポリシーなどの「30 分」の記載（[docs/aws-migration.md](aws-migration.md) の 9章）とずれる

---

## 5. コンテナの停止

### 仕組み

- アプリの EC2 は systemd の `tkb-app.service`（`Type=oneshot`、`RemainAfterExit=yes`、起動時に有効）。`ExecStart` は `/usr/local/bin/tkb-app-start`、`ExecStop` は `docker compose ... down`（[infra/terraform/templates/app-user-data.sh.tftpl](../infra/terraform/templates/app-user-data.sh.tftpl):37-56）
- `tkb-app-start` は `.env` がなければ止まる。Secrets Manager から VLM のキーを読み、内部秘密を作って `/run` に置き、`docker compose --env-file .env -f infra/docker-compose.yml up --build -d` のあと秘密のファイルを消す（[infra/tkb-app-start.sh](../infra/tkb-app-start.sh)）
- コンテナは `tkb_2613-api-1` と `tkb_2613-web-1`。どちらも `restart: unless-stopped`。api は `/health` のヘルスチェック（5 秒ごと、10 回）、web は api が healthy になってから起動（[infra/docker-compose.yml](../infra/docker-compose.yml):17-76）。web にはヘルスチェックがない
- t3.small（メモリ 2GB）に 4GB のスワップ（app-user-data:21-28）。ログは 10MB × 3 で上限（docker-compose.yml:10-15）

### 症状

| 止まったもの | 画面 | 出典 |
|---|---|---|
| web（またはアプリの EC2 そのもの） | CloudFront のエラーページ（502 / 504 が見込み。文言・ステータスは未確認） | — |
| api だけ | ページは開くが、`/api/features` が読めずパスワード欄が出る、ログイン状態の確認が失敗してログイン画面になる、ログイン・診断が「サーバーでエラーが起きました（5xx）」（中継の失敗時に Next.js が返すステータスは未確認） | [web/src/lib/api.ts](../web/src/lib/api.ts):245-260、[web/src/components/session/SessionProvider.tsx](../web/src/components/session/SessionProvider.tsx):34-42、[web/src/lib/messages.ts](../web/src/lib/messages.ts):288 |
| 診断中に api が落ちた | 「診断の途中で接続が切れました」 | api.ts:380-384、messages.ts:292 |

### 確かめ方（アプリの EC2 の中）

```bash
systemctl status tkb-app --no-pager
journalctl -u tkb-app -n 50 --no-pager
cd /opt/tkb_2613
docker compose --env-file .env -f infra/docker-compose.yml ps
docker inspect -f '{{.State.Health.Status}}' tkb_2613-api-1    # healthy であること
docker logs --tail 100 tkb_2613-api-1    # 起動時に「閲覧リンク：オフ（SHARE_ENABLED）」が出る（api/src/tkb_api/main.py:109-111）
docker logs --tail 100 tkb_2613-web-1
curl -s http://127.0.0.1:8001/health     # {"status":"ok","mock_mode":false}（api/src/tkb_api/main.py:158-160）
free -m; df -h /
```

- AWS コンソール：EC2 → `tkb_2613-app` の状態とステータスチェック。SSM で入れなければ EC2 自体を疑う
- CloudWatch：名前空間 `AWS/CloudFront`、メトリクス `5xxErrorRate`・`Requests`（ディメンション `DistributionId`、`Region=Global`。us-east-1 で見る。AWS の一般仕様で、この配信で確かめたかは未確認）
- 手元から：`curl -s https://<配信ID>.cloudfront.net/api/features`

### 直し方

| 状況 | 直し方 | 所要時間 | 副作用・注意 |
|---|---|---|---|
| 片方のコンテナだけ落ちた・固まった | `docker restart tkb_2613-api-1`（または `-web-1`）。設定と秘密はコンテナに残っているので、そのまま戻る | 数十秒（未確認） | api：全員の api セッションと診断回数が消える。web：OAuth のトークンが消え、OAuth の利用者は削除ができなくなる（ログインし直せば戻る） |
| 両方を起動し直す・設定を変えた | **`systemctl restart tkb-app`**（必ずこれ。`docker compose up` を手で打たない。README:144） | `--build` が毎回走る。キャッシュが効けば短いが、初回は十数分（README:140）。当日の実測は未確認 | `ExecStop` の `down` で全員ログアウト。web が api の healthy を待つ |
| メモリ不足で落ちる | `free -m` を見て、再起動 | 同上 | 原因（ビルドとの重なりなど）の調査は当日はしない |
| `.env` がなくて起動しない | `infra/aws.env.example` から作り直す（README:114-142） | 十数分 | 値の確認が要る。判断者の承認が要る |
| アプリの EC2 が落ちた | コンソールか `aws ec2 start-instances` で起動。`tkb-app.service` が有効なので起動時に compose も上がる（app-user-data:56） | 数分（未確認） | 内藤の認証情報が要る（予備担当は GPU を止めることしかできない） |
| 回復しない | 発表は `/demo`…ただし `/demo` も web と api を通るので、両方とも止まっていれば使えない。手元の PC で `make dev`（モック）を動かして見せる | 起動済みなら即時 | 本番ではないことを口頭で伝える |

---

## 連絡・判断の流れ

1. 気づいた人は、**症状（画面の文言・HTTP ステータス・時刻）**をチームのチャットに書く。秘密の値・投稿本文・利用者のハンドルは書かない
2. 当番がこの表の「確かめ方」で切り分ける
3. 本番を変える操作（`.env` の変更、`systemctl restart tkb-app`、`terraform apply`、GPU の手での起動、全遮断の解除、認証方式の切り戻し）は、**判断者が決めてから**行う。止める操作（全遮断を入れる、GPU を止める）は、乱用や費用の暴走があれば当番が先に行い、すぐ報告する（[docs/aws-migration.md](aws-migration.md) の 7章）
4. 発表中は、直すより先に `/demo` へ切り替えて進行を守る

| 役割 | 11/15（日） | 11/16（月） | 11/17（火） | 11/18（水） |
|---|---|---|---|---|
| 判断者（本番の変更を決める） | | | | |
| 当番（切り分け・操作。AWS の第一担当は内藤） | | | | |
| 予備（全遮断・GPU 停止だけ。谷口） | | | | |
| 発表者（`/demo` への切り替え） | | | | |

- AWS の第一担当は内藤、予備は谷口（[infra/terraform/README.md](../infra/terraform/README.md):257、[docs/aws-migration.md](aws-migration.md) の 7章）。日ごとの当番と判断者は未定（aws-migration.md の 7章の表が空欄）
