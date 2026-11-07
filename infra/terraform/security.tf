# VPC の既定のセキュリティグループは使わないので、ルールを空にしておく
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "tkb_2613-default-unused" }
}

# --- アプリの EC2：内向きは CloudFront の VPC origin から web（3000）だけ ---

resource "aws_security_group" "app" {
  name        = "tkb_2613-app"
  description = "web (3000) from CloudFront VPC origin only. No SSH."
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "tkb_2613-app" }
}

# VPC origin は、CloudFront が VPC の中に作る「CloudFront-VPCOrigins-Service-SG」から届く。
# この SG は VPC origin を作ったあとにできるので、apply のときに名前で探す（plan では known after apply）
data "aws_security_group" "cloudfront_vpc_origin" {
  vpc_id = aws_vpc.main.id
  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG"]
  }
  depends_on = [aws_cloudfront_vpc_origin.app]
}

resource "aws_vpc_security_group_ingress_rule" "app_web_from_cloudfront" {
  security_group_id            = aws_security_group.app.id
  description                  = "web from CloudFront VPC origin"
  ip_protocol                  = "tcp"
  from_port                    = 3000
  to_port                      = 3000
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origin.id
}

resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  description       = "Bluesky, cdn.bsky.app, SSM, Secrets Manager, GitHub, dnf, image registries"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "app_to_vlm" {
  security_group_id            = aws_security_group.app.id
  description                  = "VLM on the GPU"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.gpu.id
}

resource "aws_vpc_security_group_egress_rule" "app_to_ocr" {
  security_group_id            = aws_security_group.app.id
  description                  = "OCR on the GPU"
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.gpu.id
}

# --- GPU：内向きはアプリからの 8000（VLM）と 8080（OCR）だけ。外向きは 443 だけ ---

resource "aws_security_group" "gpu" {
  name        = "tkb_2613-gpu"
  description = "VLM (8000) and OCR (8080) from the app only. No SSH, no public IP."
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "tkb_2613-gpu" }
}

resource "aws_vpc_security_group_ingress_rule" "gpu_vlm_from_app" {
  security_group_id            = aws_security_group.gpu.id
  description                  = "VLM from the app"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_ingress_rule" "gpu_ocr_from_app" {
  security_group_id            = aws_security_group.gpu.id
  description                  = "OCR from the app"
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_egress_rule" "gpu_https" {
  security_group_id = aws_security_group.gpu.id
  description       = "Hugging Face, image registries, SSM, Secrets Manager"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
