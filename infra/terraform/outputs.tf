# アカウント番号の入る ARN は出さない

output "cloudfront_url" {
  description = "公開する URL"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "gpu_private_ip" {
  description = "GPU のプライベート IP。.env の VLM_BASE_URL・OCR_BASE_URL・MODEL_ALLOWED_HOST_SUFFIXES に入れる"
  value       = aws_instance.gpu.private_ip
}

output "app_instance_id" {
  description = "SSM で入るアプリの EC2"
  value       = aws_instance.app.id
}

output "gpu_instance_id" {
  description = "GPU の EC2（全遮断の手順で止める）"
  value       = aws_instance.gpu.id
}

output "vlm_secret_name" {
  description = "VLM のキーを入れる Secrets Manager のシークレット（値は README の手順で別に入れる）"
  value       = aws_secretsmanager_secret.vlm_api_key.name
}

output "kill_switch_ip_set" {
  description = "全遮断の IP セット（README の手順で使う）"
  value = {
    name  = aws_wafv2_ip_set.block_all.name
    id    = aws_wafv2_ip_set.block_all.id
    scope = "CLOUDFRONT"
  }
}

output "env_for_app" {
  description = "アプリの EC2 の .env に入れる値（infra/aws.env.example の <...> を置き換える。キーは入らない）"
  value = {
    CORS_ORIGINS                = jsonencode(["https://${aws_cloudfront_distribution.main.domain_name}"])
    VLM_BASE_URL                = "http://${aws_instance.gpu.private_ip}:8000/v1"
    VLM_MODEL                   = var.vlm_served_name
    OCR_BASE_URL                = var.ocr_image != "" ? "http://${aws_instance.gpu.private_ip}:8080" : ""
    MODEL_ALLOWED_HOST_SUFFIXES = aws_instance.gpu.private_ip
    PUBLIC_WINDOWS = jsonencode([
      for w in var.public_windows : {
        start = "${w.date}T${w.open}:00+09:00"
        end   = "${w.date}T${w.close}:00+09:00"
      }
    ])
  }
}
