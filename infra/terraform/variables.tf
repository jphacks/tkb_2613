variable "region" {
  description = "リージョン。CloudFront の WAF は us-east-1 にしか作れない"
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "NAT とアプリのサブネットを置く AZ"
  type        = string
  default     = "us-east-1a"
}

variable "gpu_availability_zone" {
  description = "GPU のサブネットを置く AZ。容量不足時は別の AZ に変更する（移動時は GPU を作り直す）"
  type        = string
  default     = "us-east-1c"
}

variable "alert_email" {
  description = "Budgets の通知の送り先。terraform.tfvars に書く（コミットしない）"
  type        = string
}

# --- 予算（docs/aws-migration.md の 6章） ---

variable "budget_limit_usd" {
  description = "月の予算（ドル）"
  type        = number
  default     = 100
}

variable "budget_alert_step_usd" {
  description = "実績がこの額の倍数（$10, $20, ... 予算まで）を超えるたびにメールで知らせる"
  type        = number
  default     = 10

  validation {
    condition     = var.budget_alert_step_usd > 0 && floor(var.budget_alert_step_usd) == var.budget_alert_step_usd
    error_message = "1 以上の整数にする"
  }
}

variable "budget_notifications_per_budget" {
  description = "1つの Budget に付ける通知の数。AWS の CreateBudget の説明の上限（5）に合わせる。これを超える分は Budget を分ける"
  type        = number
  default     = 5

  validation {
    condition     = var.budget_notifications_per_budget >= 1 && var.budget_notifications_per_budget <= 5
    error_message = "1〜5 にする（CreateBudget の説明では、1つの Budget の通知は5つまで）"
  }
}

variable "budget_stop_gpu_usd" {
  description = "この額（実績）を超えたら、Budgets action で GPU を自動で止める"
  type        = number
  default     = 80
}

# --- インスタンス ---

variable "app_instance_type" {
  description = "web と api を動かす EC2。Next.js のビルドのためにスワップを足す"
  type        = string
  default     = "t3.small"
}

variable "gpu_instance_type" {
  description = "VLM と OCR を動かす EC2。本番は g6e.xlarge（L40S 48GB）、確認用に g6.xlarge（L4 24GB）"
  type        = string
  default     = "g6e.xlarge"
}

variable "gpu_private_ip" {
  description = "GPU のプライベート IP（固定）。.env の VLM_BASE_URL・OCR_BASE_URL・MODEL_ALLOWED_HOST_SUFFIXES に入れる"
  type        = string
  default     = "10.0.2.10"
}

variable "gpu_root_volume_gb" {
  description = "GPU のディスク（重み約30GB＋イメージ）"
  type        = number
  default     = 150
}

# --- モデル ---

variable "vllm_image" {
  description = "vLLM のコンテナイメージ。初回 apply で動作を確認した版に固定する"
  type        = string
  default     = "vllm/vllm-openai:latest"
}

variable "vlm_model" {
  description = "Hugging Face のモデル。確認用の g6.xlarge では QuantTrio/Qwen3.6-27B-AWQ"
  type        = string
  default     = "Qwen/Qwen3.6-27B-FP8"
}

variable "vlm_served_name" {
  description = "api が VLM_MODEL に入れる名前"
  type        = string
  default     = "qwen3.6-27b"
}

variable "vllm_gpu_memory_utilization" {
  description = "vLLM が使う GPU のメモリの割合。OCR を同居させる分を空ける（11/11 に計測して決める）"
  type        = number
  default     = 0.85
}

variable "ocr_image" {
  description = "PP-OCRv5 の HTTP サービスのコンテナイメージ。空なら OCR を動かさない（11/12 までに枠が出なければ外す）"
  type        = string
  default     = ""
}

variable "ocr_container_port" {
  description = "OCR のコンテナの中のポート。ホストの 8080 につなぐ"
  type        = number
  default     = 8080
}

# --- アプリ ---

variable "repo_url" {
  description = "アプリの EC2 が clone するリポジトリ（公開）"
  type        = string
  default     = "https://github.com/jphacks/tkb_2613.git"
}

variable "repo_ref" {
  description = "clone するブランチかタグ"
  type        = string
  default     = "main"
}

variable "compose_version" {
  description = "Docker Compose のプラグインのバージョン（Amazon Linux 2023 の dnf には入っていない）"
  type        = string
  default     = "v2.29.7"
}

variable "buildx_version" {
  description = "Docker Buildx のプラグインのバージョン（compose up --build で使う）"
  type        = string
  default     = "v0.18.0"
}

# --- 公開時間帯（docs/aws-migration.md の 6.3）。時刻は日本時間 ---

variable "public_windows" {
  description = "GPU を動かす日。gpu_start に GPU を起動し、gpu_stop に止める。open〜close は利用規約に書く主な時間帯の目安で、アプリの制限には使わない"
  type = list(object({
    date      = string # 2026-11-16
    gpu_start = string # 19:45
    open      = string # 20:00
    close     = string # 22:00
    gpu_stop  = string # 22:00
  }))
  default = [
    # Award Day。発表に合わせて変える
    { date = "2026-11-15", gpu_start = "10:15", open = "11:00", close = "16:20", gpu_stop = "16:30" },
    { date = "2026-11-16", gpu_start = "19:45", open = "20:00", close = "22:00", gpu_stop = "22:00" },
    { date = "2026-11-17", gpu_start = "19:45", open = "20:00", close = "22:00", gpu_stop = "22:00" },
    { date = "2026-11-18", gpu_start = "19:45", open = "20:00", close = "22:00", gpu_stop = "22:00" },
  ]

  validation {
    condition = alltrue([
      for w in var.public_windows :
      can(regex("^\\d{4}-\\d{2}-\\d{2}$", w.date)) &&
      alltrue([for t in [w.gpu_start, w.open, w.close, w.gpu_stop] : can(regex("^\\d{2}:\\d{2}$", t))]) &&
      try(
        tonumber(replace(w.gpu_start, ":", "")) <= tonumber(replace(w.open, ":", "")) &&
        tonumber(replace(w.open, ":", "")) < tonumber(replace(w.close, ":", "")) &&
        tonumber(replace(w.close, ":", "")) <= tonumber(replace(w.gpu_stop, ":", "")),
        false
      )
    ])
    error_message = "date は YYYY-MM-DD、時刻は HH:MM。gpu_start <= open < close <= gpu_stop にする"
  }
}

# --- WAF（docs/aws-migration.md の 4章） ---

variable "rate_limit_all" {
  description = "IP ごとの5分あたりの全体のリクエスト数（Next.js の静的ファイルは数えない）。1つの IP から大勢が来る会場や大学を考えて、計画書の 300 より多めにする"
  type        = number
  default     = 600
}

variable "rate_limit_login" {
  description = "IP ごとの5分あたりの POST /api/session（パスワードの総当たりの踏み台にさせない）。WAF の下限は 10"
  type        = number
  default     = 10
}

variable "rate_limit_diagnose" {
  description = "IP ごとの5分あたりの POST /api/diagnose。WAF の下限が 10 なので、計画書の 5 ではなく 10"
  type        = number
  default     = 10
}

variable "killswitch_user_name" {
  description = "予備の担当（谷口）が全遮断と GPU の停止だけをできる IAM ユーザー"
  type        = string
  default     = "tkb_2613-killswitch"
}
variable "oauth_test_ipv4_cidrs" {
  description = "OAuth の公開前通し試験で許可するチームの IPv4 CIDR。空なら制限しない"
  type        = list(string)
  default     = []
}
