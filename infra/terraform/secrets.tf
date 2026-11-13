# VLM のキーの入れ物だけを作る。値は Terraform で扱わない（state に入れない）。README の手順で別に入れる
resource "aws_secretsmanager_secret" "vlm_api_key" {
  name        = "tkb_2613/vlm-api-key"
  description = "vLLM の --api-key（VLLM_API_KEY）。アプリと GPU の起動スクリプトが読む"
  # terraform destroy ですぐ消す（復元の待ち期間を置かない）
  recovery_window_in_days = 0
}

# X の OAuth confidential client secret。値は Terraform で扱わず、手作業で入れる
resource "aws_secretsmanager_secret" "x_client_secret" {
  name                    = "tkb_2613/x-client-secret"
  description             = "X OAuth 2.0 Web App の Client Secret（API コンテナだけが読む）"
  recovery_window_in_days = 0
}
