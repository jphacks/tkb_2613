# infra/terraform（AWS で一般公開する構成）

構成と理由は [docs/aws-migration.md](../../docs/aws-migration.md)。ここは作り方・使い方・消し方の手順書。

- リージョンは us-east-1。CloudFront（＋WAF）→ VPC origin → アプリの EC2（プライベート）→ GPU の EC2（プライベート、固定 IP 10.0.2.10）
- 全リソースに `Project=tkb_2613` のタグが付く（provider の `default_tags`）
- **`terraform apply` は承認を得てから行う**。このリポジトリでは plan までしか流していない

## 作るもの（plan で 53 件）

| 種類 | 内容 |
|---|---|
| ネットワーク | VPC、パブリック（NAT だけ）・アプリ・GPU のサブネット、NAT Gateway、ルート |
| セキュリティグループ | アプリ：CloudFront の VPC origin から 3000 だけ。GPU：アプリから 8000（VLM）・8080（OCR）だけ。外向きは 443（アプリは初回の dnf のため 80 も）。SSH はどちらも開けない |
| EC2 | アプリ（t3.small、Amazon Linux 2023）、GPU（g6e.xlarge、Deep Learning AMI）。どちらもパブリック IP なし、IMDSv2 必須・hop limit 1、ディスク暗号化 |
| 入口 | CloudFront（`*.cloudfront.net`、HTTPS へのリダイレクト、`/api/*` はキャッシュも圧縮もしない、IPv6 オフ）、VPC origin |
| WAF | 全遮断（IP セット）、IP の評判リスト、`/api/detect` の遮断、レート制限（ログイン 10・診断 10・全体 600／5分／IP。全体は静的ファイルを数えない）。パスは URL のデコードと正規化をしてから比べる（`/api/%73ession` ですり抜けさせない）。ログは保存しない |
| 秘密の値 | Secrets Manager の入れ物 `tkb_2613/vlm-api-key`（値は Terraform で扱わない） |
| IAM | アプリと GPU のロール（SSM ＋ キーの読み取りだけ）、全遮断の予備の担当の IAM ユーザー、Budgets action とスケジュールのロール |
| 予算 | 月 $100。実績 $50 でメール、予測 $100 でメール、**実績 $80 で GPU を自動で止め、スケジュールでの再起動も止める** |
| スケジュール | 公開日ごとに GPU を起動・停止（下の表） |

### GPU のスケジュール（日本時間）

| 日 | GPU の起動 | 公開 | GPU の停止 |
|---|---|---|---|
| 11/15（Award Day） | 10:15 | 11:00〜16:20 | 16:30 |
| 11/16・17・18 | 19:45 | 20:00〜22:00 | 22:00 |

変えるときは `terraform.tfvars` の `public_windows` を書いて apply し、出力の `env_for_app.PUBLIC_WINDOWS` を `.env` に入れ直す（利用規約の公開日時 `web/src/lib/legal.ts` の `PUBLIC_SCHEDULE` も合わせる）。

## VLM のキーの渡し方（決定）

**起動スクリプトが Secrets Manager から読み、メモリ上のファイルでコンテナに渡す**（docs/aws-migration.md の 10.1 の案 A）。

- アプリ：`tkb-app-start`（systemd の `tkb-app.service`）がインスタンスロールでキーを読み、`/run/tkb_2613/secrets.env`（`/run` は tmpfs＝メモリ）に書いて `docker compose up` し、終わったら消す。compose はこのファイルを2つめの `env_file` として読む（`infra/docker-compose.yml`）。後に読むほうが優先されるので、`.env` の空の `VLM_API_KEY` を上書きする。手元にはこのファイルがないので、手元の動きは変わらない
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

## apply（承認を得てから）

最初の apply は2回に分ける。アプリの受け入れ元のセキュリティグループ（`CloudFront-VPCOrigins-Service-SG`）は、VPC origin ができたあとに CloudFront が作るので、先に VPC origin まで作る。

```bash
terraform apply -target=aws_cloudfront_vpc_origin.app
terraform plan -out=review.tfplan
terraform apply review.tfplan
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

## アプリの .env を作る

GPU のプライベート IP などは `terraform output` で出る。キーは `.env` に書かない。

```bash
terraform output gpu_private_ip      # 10.0.2.10
terraform output -json env_for_app   # .env に入れる値（CORS_ORIGINS・VLM_BASE_URL・OCR_BASE_URL・MODEL_ALLOWED_HOST_SUFFIXES・PUBLIC_WINDOWS）
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
          #   PUBLIC_WINDOWS=（env_for_app.PUBLIC_WINDOWS の値を1行で）
          # VLM_API_KEY は空のまま（起動スクリプトが渡す）
systemctl start tkb-app     # 初回はイメージのビルドで十数分かかる
journalctl -u tkb-app -n 50 --no-pager
```

**起動し直すときは、必ず `systemctl restart tkb-app` を使う**。`docker compose up` を手で打つと、キーのファイルがないので、api が空のキーで起動する（モデルにつながらず「準備中」になる）。

推理の表（`data/processed`）は EC2 の上にはない。なくても動く（最寄り駅のルールだけを飛ばす）。入れるときは手元で `make data` してから、SSM で `/opt/tkb_2613/data/processed` に置く（方法は要確認）。

### 起動したら確かめる

- `curl -s https://<配信ID>.cloudfront.net/api/features` が `{"share_enabled":false}`（閲覧リンクがオフ）
- アプリの EC2 で `docker logs tkb_2613-api-1 2>&1 | grep 閲覧リンク` が「閲覧リンク：オフ（SHARE_ENABLED）」
- 公開時間外に診断すると「公開時間外です。次は…からです」

## 全遮断・停止（docs/aws-migration.md の 7章）

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

## 要確認

- `vllm_image`：既定は `vllm/vllm-openai:latest`。RunPod と同じバージョンに固定する
- `ocr_image`：PP-OCRv5 の HTTP サービスのイメージ。決まるまでは空（OCR を動かさない）
- VPC origin から届くセキュリティグループの名前（`CloudFront-VPCOrigins-Service-SG`）。apply で見つからなければ、`security.tf` の受け入れ元を VPC の CIDR にする
- CloudFront の既定の証明書では、TLS の最低バージョンを指定できない（TLS 1.2 以上にしたいときは独自ドメインと ACM が要る）
- `compose_version`・`buildx_version`：Amazon Linux 2023 に入れる Docker のプラグインのバージョン
