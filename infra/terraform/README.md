# infra/terraform（AWS で一般公開する構成）

構成と理由は [docs/aws-migration.md](../../docs/aws-migration.md)。ここは作り方・使い方・消し方の手順書。

- リージョンは us-east-1。CloudFront（＋WAF）→ VPC origin → アプリの EC2（プライベート）→ GPU の EC2（プライベート、固定 IP 10.0.2.10）
- 全リソースに `Project=tkb_2613` のタグが付く（provider の `default_tags`）
- **`terraform apply` は承認を得てから行う**。OAuth 変更も plan を確認してから反映し、apply のたびに state をリポジトリ外へコピーする

## 作るもの

| 種類 | 内容 |
|---|---|
| ネットワーク | VPC、パブリック（NAT だけ）・アプリ・GPU のサブネット、NAT Gateway、ルート |
| セキュリティグループ | アプリ：CloudFront の VPC origin から 3000 だけ。GPU：アプリから 8000（VLM）・8080（OCR）だけ。外向きは 443（アプリは初回の dnf のため 80 も）。SSH はどちらも開けない |
| EC2 | アプリ（t3.small、Amazon Linux 2023）、GPU（g6e.xlarge、Deep Learning AMI）。どちらもパブリック IP なし、IMDSv2 必須・hop limit 1、ディスク暗号化 |
| 入口 | CloudFront（`*.cloudfront.net`、HTTPS へのリダイレクト、`/api/*` と `/auth/*` はキャッシュも圧縮もしない、IPv6 オフ）、VPC origin |
| WAF | 全遮断（IP セット）、公開前試験のチーム IP 制限、IP の評判リスト、`/api/detect` と Next.js の内部経路 `/__internal`（2回デコードしてから比べる）の遮断、レート制限（ログイン 10・診断 10・全体 600／5分／IP。全体は静的ファイルを数えない）。パスは URL のデコードと正規化をしてから比べる（`/api/%73ession` ですり抜けさせない）。ログは保存しない |
| 秘密の値 | Secrets Manager の入れ物 `tkb_2613/vlm-api-key`（値は Terraform で扱わない） |
| IAM | アプリと GPU のロール（SSM ＋ キーの読み取りだけ）、全遮断の予備の担当の IAM ユーザー、Budgets action とスケジュールのロール |
| 予算 | 月 $100。**実績が $10, $20, … $100 を超えるたびにメール**（Budget を2つに分ける。下の「予算の通知」）。**実績 $80 で GPU を自動で止め、スケジュールでの再起動も止める** |
| スケジュール | 公開日ごとに GPU を起動・停止（下の表） |

### GPU のスケジュール（日本時間）

| 日 | GPU の起動 | 公開 | GPU の停止 |
|---|---|---|---|
| 11/15（Award Day） | 10:15 | 11:00〜16:20 | 16:30 |
| 11/16・17・18 | 19:45 | 20:00〜22:00 | 22:00 |

変えるときは `terraform.tfvars` の `public_windows` を書いて apply する（利用規約の時間帯 `web/src/lib/legal.ts` の `PUBLIC_SCHEDULE` も合わせる）。

アプリの `PUBLIC_WINDOWS` は空（`[]`）にし、公開時間で診断を断らない（2026-11-10 決定）。診断できるのは GPU が動いている間だけで、止まっていれば画面は「準備中」になる。**GPU を手で起動すると、その間は誰でも診断できる**。

## VLM のキーの渡し方（決定）

**起動スクリプトが Secrets Manager から読み、メモリ上のファイルでコンテナに渡す**（docs/aws-migration.md の 10.1 の案 A）。

- アプリ：`tkb-app-start`（systemd の `tkb-app.service`）がインスタンスロールでVLMキーと、設定済みならX Client Secretを読み、`/run/tkb_2613/api-secrets.env`（`/run` は tmpfs＝メモリ）に書いて `docker compose up` し、終わったら消す。OAuth 用の内部共有秘密は起動のたびに生成し、api と web に別の一時ファイルで渡す。web にはVLMキーもX Secretも渡さない。後に読むほうが優先されるので、`.env` の空の値を上書きする
- GPU：`tkb-vllm.service` が起動のたびに同じようにキーを読み、`VLLM_API_KEY` として vLLM に渡す

案 B（api が IAM ロールで Secrets Manager を直接読む）にしなかった理由：

1. コンテナからインスタンスのメタデータに届くようにする（hop limit 2）必要がある。そうすると、api のコンテナが乗っ取られたときにインスタンスの認証情報まで取られる。hop limit 1 を守るほうが大事
2. api に AWS の SDK の依存が増え、手元・CI・AWS で動きが変わる

残る点（再検査 13.2 で確かめる）：キーはコンテナの設定として、ホストの `docker inspect` と `/var/lib/docker`（暗号化した EBS）に入る。見られるのは SSM でホストに入れる管理者だけ。`.env`・ユーザーデータ・Terraform の state・ログには入らない。

## 準備（初回だけ）

- Terraform 1.9 以上（入っていなければ Docker で `hashicorp/terraform:1.9.8` を使う。下の「Docker で動かす」）
- AWS CLI の認証先が内藤のアカウントであること（`aws sts get-caller-identity`。アカウント番号はどこにも貼らない）
- GPU の上限（`L-DB2E81BA`、Running On-Demand G and VT instances）が 8 vCPU 以上に上がっていること。**上がっていないと、GPU を作るところで apply が止まる**（6.4 の代替案）

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # alert_email を書く（コミットしない）
terraform init
terraform plan -out=review.tfplan
```

### Docker で動かす

```bash
cd infra/terraform
alias tf='docker run --rm -it -u "$(id -u):$(id -g)" -e HOME=/tmp -e AWS_REGION=us-east-1 \
  -v "$HOME/.aws:/tmp/.aws:ro" -v "$PWD:/work" -w /work hashicorp/terraform:1.9.8'
tf init && tf plan -out=review.tfplan
```

### GPU の AZ を変えるとき

`availability_zone` は NAT とアプリ用（既定 `us-east-1a`）、`gpu_availability_zone` は GPU 用（既定 `us-east-1c`）。2026-11-08 に GPU を `us-east-1c` に移した。GPU の容量不足時は `terraform.tfvars` の `gpu_availability_zone` だけを、`g6e.xlarge` が提供される別の AZ に変える。提供の有無は空き容量の保証ではない。

GPU の AZ を変える plan では、GPU のサブネット・ルートテーブル関連付け・EC2 が作り直しになり、新しい GPU の ID を参照するスケジュール、IAM ポリシー、Budgets action が更新される。2026-11-08 の plan では、アプリの EC2、VPC、NAT、CloudFront の作り直しは出ていない。GPU の固定 IP（`10.0.2.10`）は同じだが、今の GPU のルートディスクは終了時に削除されるため、モデルの重みとコンテナイメージは再取得になる。

apply 前に plan の差分を確認し、state をリポジトリ外へコピーする。別 AZ でも起動に必要な空き容量は保証されず、GPU と NAT が別 AZ になると AZ 間の通信費がかかる。`terraform apply` は承認後にだけ行う。

## apply（承認を得てから）

最初の apply は2回に分ける。VPC origin を作るには、VPC に Internet Gateway（IGW）が付いている必要がある。`aws_cloudfront_vpc_origin.app` は IGW に明示的に依存しているため、最初の `-target` でも IGW が先に作られる。アプリの受け入れ元のセキュリティグループ（`CloudFront-VPCOrigins-Service-SG`）は、VPC origin ができたあとに CloudFront が作るので、先に VPC origin まで作る。

```bash
terraform apply -target=aws_cloudfront_vpc_origin.app
# ここで下の「apply のたびに state をリポジトリの外へコピーする」を実施
terraform plan -out=review.tfplan
terraform apply review.tfplan
# ここでも state をコピー
```

2回めでも「no matching SecurityGroup」で止まったら、数分待ってもう一度 apply する。それでも見つからなければ、`security.tf` の受け入れ元を VPC の CIDR にする（要確認）。

- **GPU は作った直後から動いて課金が始まる**。初回は重み（約30GB）の取得に時間がかかるので、取得が終わって動作を確かめたら止める（下の「GPU を止める」）。以降はスケジュールで起動・停止する
- CloudFront の配信と VPC origin は、できるまで15分ほどかかる

### apply のたびに state をリポジトリの外へコピーする

state（`terraform.tfstate`）はこの PC にしかない。なくすと `terraform destroy` で消せなくなるので、apply のたびにリポジトリの外へコピーする。state にはキーの値は入らないが、ARN（アカウント番号を含む）が入るので、公開の場所には置かない。

```bash
mkdir -p ~/tkb_2613-tfstate
cp terraform.tfstate ~/tkb_2613-tfstate/terraform.tfstate.$(date +%Y%m%d-%H%M%S)
```

## キーを入れる（apply のあと、初回だけ）

値を画面やシェルの履歴に残さないように入れる。キーを変えたら、GPU とアプリの両方を起動し直す。

```bash
read -rs VLM_KEY   # 貼り付けて Enter（画面に出ない）
aws secretsmanager put-secret-value --secret-id tkb_2613/vlm-api-key --secret-string "$VLM_KEY"
unset VLM_KEY
```

X連携を有効にする場合だけ、Developer Consoleで再生成したClient Secretを別のSecretへ入れる。値は `.env` やコマンドライン引数に書かない。

```bash
read -rs X_OAUTH_SECRET   # 貼り付けて Enter（画面に出ない）
aws secretsmanager put-secret-value --secret-id tkb_2613/x-client-secret --secret-string "$X_OAUTH_SECRET"
unset X_OAUTH_SECRET
```

## アプリの .env を作る

GPU のプライベート IP などは `terraform output` で出る。キーは `.env` に書かない。

```bash
terraform output gpu_private_ip      # 10.0.2.10
terraform output -json env_for_app   # .env に入れる値（CORS_ORIGINS・VLM_BASE_URL・OCR_BASE_URL・MODEL_ALLOWED_HOST_SUFFIXES・PUBLIC_WINDOWS=[]）
```

SSM でアプリの EC2 に入り、見本から `.env` を作って起動する。

```bash
aws ssm start-session --target "$(terraform output -raw app_instance_id)"
# ここからアプリの EC2 の中
sudo -i
cd /opt/tkb_2613
cp infra/aws.env.example .env
vi .env   # <...> を terraform output の値に置き換える
          #   VLM_BASE_URL=http://10.0.2.10:8000/v1
          #   OCR_BASE_URL=http://10.0.2.10:8080（OCR を動かさないなら空）
          #   MODEL_ALLOWED_HOST_SUFFIXES=10.0.2.10
          #   CORS_ORIGINS=["https://<配信ID>.cloudfront.net"]
          #   PUBLIC_WINDOWS=[]（公開時間では制限しない）
# VLM_API_KEY と X_CLIENT_SECRET は空のまま（起動スクリプトが渡す）
# OAuth の場合は AUTH_MODE=oauth、PUBLIC_URL=https://<配信ID>.cloudfront.net、
# OAUTH_WEB_ORIGIN=http://web:3000。INTERNAL_AUTH_SECRET は .env に書かない
systemctl start tkb-app     # 初回はイメージのビルドで十数分かかる
journalctl -u tkb-app -n 50 --no-pager
```

**起動し直すときは、必ず `systemctl restart tkb-app` を使う**。`docker compose up` を手で打つと、キーのファイルがないので、api が空のキーで起動する（モデルにつながらず「準備中」になる）。

推理の表（`data/processed`）はリポジトリにもイメージにも入っていない。なくても動く（最寄り駅・公開データのルールを飛ばす）が、本番では次の「推理の表を届ける」で入れる。

## 推理の表を届ける（data/processed）

手元で作った表を tar にして S3 に上げ、**期限の短い署名付き URL** を作る。アプリの EC2 はその URL から HTTPS（NAT 経由）で取るだけで、**EC2 のロールに S3 の権限は足さない**。スクリプトは作ってあるだけで、実行は人が行う。

| スクリプト | 実行する場所 | すること |
|---|---|---|
| `infra/upload-processed-data.sh <バケット名> [秒数]` | 手元（Linux・WSL。GNU tar と aws CLI） | 表がそろっているか確かめ、tar（中の各表の sha256 つき）を S3 に上げ、署名付き URL（既定 900 秒、最大 3600 秒）と tar の sha256 を出す。バケットの公開アクセスのブロックが全部オンでなければ止まる |
| `infra/install-processed-data.sh <tar の sha256>` | アプリの EC2（SSM、root） | URL を聞く（引数にしないので履歴に残らない）。取って sha256 と中身（決まった名前の普通のファイルだけ）を確かめ、`/opt/tkb_2613/data/processed` を入れ替え（前の表は `processed.prev`）、`systemctl restart tkb-app` する |

tar に入れる表（11個。1つでも欠けたら上げない）：`stations`・`postal`・`area_codes`・`muni_mesh`・`households_500m`（e-Stat のメッシュ統計から）・`schools`・`shelters`・`bus_stops`・`school_districts`・`ridership` の `.parquet` と、法人番号の `corporations.sqlite`。固めると約 75MB、展開すると約 220MB。

任意で、写真場所のPOI索引 `places.sqlite3`（国土数値情報 P05 の役場・公的集会施設など。作り方は [data-prep/SOURCES.md](../../data-prep/SOURCES.md)）も入れる。`data/processed/places.sqlite3` があればそれを、なければ `data/processed/national/places.sqlite3` を使い、どちらの場合も tar では直下に置く。本番の api は11個がそろった `data/processed` を選び、POI索引もその直下だけを見るため、`national/` の下のままでは使われない。索引がなければ写真場所の候補はいつも「不明」になる（他の推理には影響しない）。P05 全国版で約 100MB 増える。Overture Maps Places の関東1都6県分（約103万件）を足した索引は約 2GB（P05 のみは約 100MB）で、tar に入れると約 2GB が S3 経由で EC2 に届き、展開後も約 2GB のディスクを使うので、EC2 のディスクの空きと署名付き URL の有効秒数（既定 900 秒、最大 3600 秒）を先に確かめる。置き場所は同じく `data/processed/places.sqlite3` で、作り方は [data-prep/SOURCES.md](../../data-prep/SOURCES.md) の「Overture Places 関東1都6県の索引」（`data/processed/kanto/places.sqlite3` を `data/processed/` 直下へコピーする）。索引の schema version（`PRAGMA user_version`）が api と合わないものは api が読まないので、api を更新したら索引も作り直して届け直す。

### 1. 手元で表を作る

e-Stat の地域メッシュ統計（`data-prep/raw/estat/`）と国税庁の法人番号の zip（`data-prep/raw/houjin/`）は、どちらもブラウザで落として手で置く（[data-prep/README.md](../../data-prep/README.md)）。置いたら：

```bash
make data
ls -l data/processed   # 上の 11 個があること
```

### 2. バケットを用意する（初回だけ）

表だけを置く非公開のバケット。Terraform では作らない（消すときは下の「消す」で一緒に消す）。

```bash
BUCKET=tkb-2613-processed-$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --region us-east-1 --bucket "$BUCKET"
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=Project,Value=tkb_2613}]'
```

### 3. 上げて、署名付き URL を作る

```bash
infra/upload-processed-data.sh "$BUCKET"        # 期限を変えるなら 2つめの引数に秒数（60〜3600）
```

最後に、EC2 で打つコマンド（tar の sha256 つき）と URL が出る。**URL は期限内なら誰でも取れるので、チャットや Issue に貼らず、SSM のセッションにだけ貼る**。期限が切れたら、もう一度このスクリプトを実行する。

### 4. アプリの EC2 で取って入れ替える

EC2 のリポジトリは、このスクリプトを含むコミット以降にしておく（下の「既存 EC2 の起動スクリプト更新」と同じく `git fetch` と `git checkout`）。

```bash
aws ssm start-session --target "$(terraform output -raw app_instance_id)"
# ここからアプリの EC2 の中
sudo -i
/opt/tkb_2613/infra/install-processed-data.sh <手元に出た sha256>
# 「署名付き URL:」と聞かれたら貼って Enter（画面に出ない）
```

### 5. 手元で S3 の tar を消す

```bash
aws s3 rm "s3://$BUCKET/processed/<上げたファイル名>"
```

### 表を届けたら確かめる

- アプリの EC2 で `docker logs tkb_2613-api-1 2>&1 | grep 推理の表` が何も出さない（出れば表を読めていない。「推理の表を読めませんでした（…）」の括弧の中が原因の種類）
- `curl -s https://<配信ID>.cloudfront.net/api/demo/diagnosis | jq -r '.conclusions[] | "\(.attribute)=\(.value)"'` に次が出る（表がないと出ない）
  - `station=根津駅`
  - `home_district=文京区 弥生1・2丁目`
  - `home_area=弥生`、`home_block=弥生二丁目付近`
- ブラウザで `https://<配信ID>.cloudfront.net/demo` を開き、推理の結論に「最寄り駅：根津駅」と「ゴミの収集地区：文京区 弥生1・2丁目」が出る
- アプリの EC2 で `docker stats --no-stream tkb_2613-api-1` のメモリが、表を入れる前より約 72MB 増えた程度（法人番号の SQLite はメモリに載せず、引くたびにディスクから読む）
- `ls -l /opt/tkb_2613/data/processed` が 11 個（POI索引を入れたら `places.sqlite3` を足して 12 個）で、どれも `-rw-r--r--`

### 表を戻す

入れ替えた表で困ったら、前の表に戻して再起動する。

```bash
cd /opt/tkb_2613/data
mv processed processed.bad && mv processed.prev processed && systemctl restart tkb-app
```

### 起動したら確かめる

- `curl -s https://<配信ID>.cloudfront.net/api/features` が `share_enabled=false` と設定した `auth_mode` を返す
- アプリの EC2 で `docker logs tkb_2613-api-1 2>&1 | grep 閲覧リンク` が「閲覧リンク：オフ（SHARE_ENABLED）」
- GPU を止めた状態で診断すると「ただいま準備中です」

## GitHub Actions から本番デプロイする

リポジトリに書き込めるメンバーなら誰でも、Actions の「本番デプロイ」→「Run workflow」（ブランチは main のまま）で、**その時点の最新の main** を本番に出せる。中身は上の「既存 EC2 の起動スクリプト更新」と同じ手順（checkout → 起動スクリプトを入れ直す → `systemctl restart tkb-app`）。

| 段階 | 場所 | すること |
|---|---|---|
| 1 | Actions（`.github/workflows/deploy.yml`） | 最新の main か、そのコミットの CI が成功しているかを確かめる。違えば何もしない |
| 2 | Actions | OIDC でロール `tkb_2613-github-deploy` を引き受ける（長期のキーなし。main のジョブだけ） |
| 3 | Actions → SSM | ドキュメント `tkb_2613-deploy` をアプリの EC2 に送る。渡すのはコミット SHA だけ |
| 4 | アプリの EC2（`infra/deploy.sh`） | ロック → 最新の main かを再確認 → 前のイメージを `:rollback-<前のSHA>` で残す → checkout → 起動し直す |
| 5 | アプリの EC2 | api の healthcheck、web の `/` と `/api/features`、公開オリジンでの `infra/prod_smoke.py` |
| 6 | アプリの EC2 | 5 が失敗したら前のコミットに戻して起動し直し、もう一度確かめる |
| 7 | Actions | 実行者・コミット・前のコミット・結果・所要時間を、実行の Summary に出す |

- ロールにできるのは、このドキュメントをアプリの EC2 に送ることと、結果を読むことだけ。任意のシェル（`AWS-RunShellScript`）は送れず、GPU の起動・停止もできない
- `.env`・`data/processed`・`eval/local` は git の管理外なので、checkout でも変わらない。秘密は起動スクリプトが毎回 Secrets Manager から読む
- 同時には動かない（Actions の `concurrency` と、EC2 の `flock`）。追跡しているファイルを EC2 で手で直してあると、消さないように止まる
- Actions を途中で止めても、EC2 側のデプロイとロールバックは最後まで進む。結果は SSM のコマンド ID（Summary にある）で確かめる
- ロールバックは前のコミットから作り直す（ビルドのキャッシュがあれば1〜2分）。それも失敗したときは、残した `:rollback-<SHA>` のイメージと `git checkout <前のSHA>` で手で戻す

### 初回の準備（インフラ担当が1回だけ）

1. Terraform でロールとドキュメントを作る。**`-target` で、この3つだけを apply する**（2026-11-14 時点で、WAF にも main のコードとの差がある。診断のレート制限に `/api/draft-check` を足す変更で、これは別に判断する）

   ```bash
   cd infra/terraform
   terraform plan -out=deploy.tfplan \
     -target=aws_ssm_document.deploy \
     -target=aws_iam_role.github_deploy \
     -target=aws_iam_role_policy.github_deploy
   terraform apply deploy.tfplan
   # apply のたびに state をリポジトリの外へコピーする（上の「apply のたびに state を…」）
   ```

2. ロールの ARN を GitHub の **secret** `AWS_DEPLOY_ROLE_ARN` に入れる（アカウント番号を公開のログに出さないため、variable ではなく secret にする）。画面にも履歴にも出さずに入れる：

   ```bash
   aws iam get-role --role-name tkb_2613-github-deploy --query Role.Arn --output text \
     | gh secret set AWS_DEPLOY_ROLE_ARN -R jphacks/tkb_2613
   ```

3. 一度、Actions から実行して Summary が「成功」になることを確かめる

## 全遮断・停止（docs/aws-migration.md の 7章）

### OAuth の公開前試験と採用判定（11/12 21:00 JST）

1. レビュー済みのコミットを本番に配置する前に、`terraform plan -out=review.tfplan` で CloudFront の `/auth/*` 非キャッシュ設定、WAF の `/auth/start` レート制限、試験用 IP 制限の差分を確認する。承認後に apply し、直後に上記の手順で state をリポジトリ外にコピーする。`user_data` は既存 EC2 では更新されない。
2. `terraform.tfvars` の `oauth_test_ipv4_cidrs` にチームの現在のグローバル IPv4 アドレスを `/32` で入れ、plan・apply・state バックアップを行う。試験中はメタデータ以外の全経路をチーム IP だけにする。Bluesky の認可サーバーが読む `/oauth-client-metadata.json` は公開のままにする。
3. SSM セッションでアプリ EC2 に入り、レビュー済みコミットを取得し、`sudo install -m 700 /opt/tkb_2613/infra/tkb-app-start.sh /usr/local/bin/tkb-app-start` を実行する。これは既存の `user_data` からは自動反映されない。`.env` を `infra/aws.env.example` と照合し、`AUTH_MODE=oauth`、`PUBLIC_URL=https://<配信ID>.cloudfront.net`、`OAUTH_WEB_ORIGIN=http://web:3000` にする。`INTERNAL_AUTH_SECRET` は `.env` に書かない。`PUBLIC_WINDOWS=[]` を確認し、`systemctl restart tkb-app` で起動する。
4. `https://<配信ID>.cloudfront.net/oauth-client-metadata.json` が HTTPS 200・JSON・非キャッシュであること、OAuth コールバック後のブラウザ URL に `code` と `state` が残らないこと、`tkb_session` が HttpOnly・Secure・SameSite=Lax であることを確認する。専用の架空アカウントで OAuth ログイン→本人投稿取得→診断→仮除外→削除してよい1件の実削除→再診断を試す。ログに認可コード、トークン、投稿本文が出ていないこと、WAF が他 IP を遮断すること、再起動後に再ログインできることも確認する。
5. 試験後は `oauth_test_ipv4_cidrs=[]` にして plan・apply・state バックアップを行う。**11/12 21:00 JST までに AWS 経由の実削除と CI の全項目が確認できた場合だけ OAuth を採用**する。未確認項目が1つでもあれば `.env` の `AUTH_MODE=app_password` に戻し、`systemctl restart tkb-app` する。切り戻し後は App Password だけを画面で案内する。11/13 の機能凍結後は認証方式を変えない。

既存 EC2 の起動スクリプト更新は、SSM セッション内で次を実行する。`<レビュー済みコミット>` にはマージ後の SHA を入れる。Terraform の `user_data` 変更だけでは既存 EC2 に反映されない。

```bash
aws ssm start-session --target "$(terraform output -raw app_instance_id)"
# 以下はアプリ EC2 内
sudo -i
cd /opt/tkb_2613
git fetch origin main
git checkout <レビュー済みコミット>
install -m 700 infra/tkb-app-start.sh /usr/local/bin/tkb-app-start
vi .env  # AUTH_MODE、PUBLIC_URL、OAUTH_WEB_ORIGIN、PUBLIC_WINDOWS=[] を確認
systemctl restart tkb-app
```


第一担当は内藤、予備は谷口。谷口には IAM ユーザー `tkb_2613-killswitch` を渡す（アクセスキーは IAM のコンソールで発行し、チャットに貼らずに直接渡す）。このユーザーができるのは、下の 1 と 2 だけ（ほかには IP セットの一覧と EC2 の一覧を見ることだけ）。

### 1. WAF で全員を遮断する（約1分）

```bash
ID=$(aws wafv2 list-ip-sets --scope CLOUDFRONT --region us-east-1 \
  --query "IPSets[?Name=='tkb_2613-block-all'].Id" --output text)
TOKEN=$(aws wafv2 get-ip-set --scope CLOUDFRONT --region us-east-1 --name tkb_2613-block-all --id "$ID" \
  --query LockToken --output text)
aws wafv2 update-ip-set --scope CLOUDFRONT --region us-east-1 --name tkb_2613-block-all --id "$ID" \
  --lock-token "$TOKEN" --addresses 0.0.0.0/1 128.0.0.0/1
```

戻すときは、同じ手順で `--addresses '[]'` にする。

### 2. GPU を止める（約1分。画面は開けるが、診断は「準備中」になる）

```bash
aws ec2 stop-instances --region us-east-1 --instance-ids "$(terraform output -raw gpu_instance_id)"
```

谷口は、`Project=tkb_2613` と `Role=gpu` のタグが付いたインスタンスしか止められない。インスタンス ID は `aws ec2 describe-instances --filters Name=tag:Role,Values=gpu Name=tag:Project,Values=tkb_2613 --query 'Reservations[].Instances[].InstanceId'` で探せる。

### 3. CloudFront を無効にする（数分〜15分。内藤だけ）

コンソールで配信を Disable する。

### 4. 全部消す（内藤だけ）

下の「消す」。

## 予算の通知

| Budget | 通知（実績がこの額を超えたらメール） | Budgets action |
|---|---|---|
| `tkb_2613-alerts-1` | $10, $20, $30, $40, $50 | なし |
| `tkb_2613-alerts-2` | $60, $70, $80, $90, $100 | なし |
| `tkb_2613-actions` | なし | $80 で GPU を止め、スケジュールでの再起動を禁止する |

- 1つの Budget に付けられる通知は5つまでなので（[CreateBudget](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html)：「A budget can have up to five notifications」。同じページの配列の制約は10個だが、少ないほうに合わせた）、10個の通知を2つの Budget に分けている。刻みは `budget_alert_step_usd`、1つの Budget の通知の数は `budget_notifications_per_budget`
- 送り先は `terraform.tfvars` の `alert_email`。届かないときは迷惑メールのフォルダも確かめる
- **通知は、お金が使われてから数時間（長いと1日近く）遅れて届く**。AWS Budgets のデータは「最大1日3回、前の更新から8〜12時間ごと」に更新される（[Managing your costs with AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)）。別のページには「請求のデータは少なくとも1日1回更新され、通知もそれに合わせて送られる」とある（[Best practices for AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html)）。そのため、**メールが届いた時点で、書いてある額より多く使っていることがある**。$80 の自動停止も同じだけ遅れるので、実際は $80 を超えてから止まる
- 遅れがあるので、**ふだんの止め方は公開時間帯のスケジュール**で、予算の通知と自動停止は最後の安全網。公開期間中は、GPU を手で起動したら止め忘れていないかを毎回確かめる

## 予算 $80 で止まったあと

$80 を超えると、Budgets action が GPU を止め、スケジュールのロールに「起動を禁止する」ポリシー（`tkb_2613-deny-gpu-start`）を付ける。このままだと、次の公開時間帯にも GPU は起動しない（画面は「準備中」になる）。続けるかはチームで決める。続けるなら、Budgets のコンソールで action を「リセット」してから、ポリシーを外す。

```bash
aws iam detach-role-policy --role-name tkb_2613-gpu-scheduler \
  --policy-arn "$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='tkb_2613-deny-gpu-start'].Arn" --output text)"
```

NAT・WAF・アプリの EC2 は止まらない（GPU だけを止める）。全部止めるときは「消す」。

## GPU を手で起動・停止する

```bash
aws ec2 start-instances --region us-east-1 --instance-ids "$(terraform output -raw gpu_instance_id)"
aws ec2 stop-instances  --region us-east-1 --instance-ids "$(terraform output -raw gpu_instance_id)"
```

vLLM が応答するまで数分かかる。アプリの EC2 から `curl -s -o /dev/null -w '%{http_code}' http://10.0.2.10:8000/v1/models` が 401（キーなし）なら起動済み。

## 消す（docs/aws-migration.md の 12章）

| 日時 | 作業 |
|---|---|
| 11/18 22:00 | スケジュールで GPU が止まる。止まったことを確かめる |
| 11/19 | 記録用のスクリーンショット（WAF のグラフ、Budgets の実績、構成）を撮る → `terraform destroy` → RunPod の Pod を Terminate し、RunPod のキーを無効にする |
| 11/20 | 請求とタグ（Cost Explorer で `Project=tkb_2613`）で消し忘れがないか確かめる |

```bash
terraform destroy
```

- Secrets Manager のシークレットは、復元の待ち期間なしで消える
- 谷口の IAM ユーザーは、手で発行したアクセスキーごと消える（`force_destroy`）
- VPC origin が VPC の中に作るネットワークインターフェースが残っていると、サブネットや VPC の削除が数分待たされる。止まったら、少し待ってもう一度 `terraform destroy`
- 終わったら、state のコピー（`~/tkb_2613-tfstate/`）も消してよい
- 推理の表のバケット（Terraform の外で作ったもの）は手で消す：`aws s3 rb "s3://$BUCKET" --force`

## 要確認

- `vllm_image`：RunPod のログで版を確認できる記録が手元にないため、今は `vllm/vllm-openai:latest` のまま。初回の apply で動いた版に固定する
- `ocr_image`：PP-OCRv5 の HTTP サービスのイメージ。決まるまでは空（OCR を動かさない）
- VPC origin から届くセキュリティグループの名前（`CloudFront-VPCOrigins-Service-SG`）。apply で見つからなければ、`security.tf` の受け入れ元を VPC の CIDR にする
- CloudFront の既定の証明書では、TLS の最低バージョンを指定できない（TLS 1.2 以上にしたいときは独自ドメインと ACM が要る）
- `compose_version`・`buildx_version`：Amazon Linux 2023 に入れる Docker のプラグインのバージョン
