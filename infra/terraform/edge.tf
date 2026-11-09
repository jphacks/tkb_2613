# 入口は CloudFront（*.cloudfront.net の HTTPS）だけ。VPC origin で、プライベートサブネットの
# アプリの EC2 に AWS の中だけを通ってつなぐ（docs/aws-migration.md の 3.2）

resource "aws_cloudfront_vpc_origin" "app" {
  # VPC に IGW がアタッチされてから作る（VPC origin の AWS 側の要件）
  depends_on = [aws_internet_gateway.main]

  vpc_origin_endpoint_config {
    name                   = "tkb-2613-app"
    arn                    = aws_instance.app.arn
    http_port              = 3000
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Host も含めて転送する（アプリに *.cloudfront.net が届く。内部の名前でリダイレクトを作らせない）
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

locals {
  origin_id = "app"
}

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  comment         = "tkb_2613"
  is_ipv6_enabled = false            # 全遮断の IP セットを IPv4 だけで済ませる
  price_class     = "PriceClass_200" # 日本のエッジを含む
  web_acl_id      = aws_wafv2_web_acl.main.arn

  origin {
    origin_id   = local.origin_id
    domain_name = aws_instance.app.private_dns

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.app.id
      # SSE は 15 秒ごとに keep-alive が届くので、60 秒あれば切れない（3.4）
      origin_read_timeout      = 60
      origin_keepalive_timeout = 5
    }
  }

  # 画面とログイン状態の応答はキャッシュしない
  default_cache_behavior {
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    compress                   = true
  }

  # api：キャッシュせず、圧縮もしない（SSE をためこませない。api も no-store, no-transform を返す）
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    compress                   = false
  }

  # OAuth の開始 POST とコールバック GET。認可コードをキャッシュしない
  ordered_cache_behavior {
    path_pattern               = "/auth/*"
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    compress                   = false
  }

  # Next.js の静的ファイル（ファイル名にハッシュが入る）はキャッシュしてよい
  ordered_cache_behavior {
    path_pattern               = "/_next/static/*"
    target_origin_id           = local.origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  # ログの保存先は作らない（決定事項 14.1 の5）
}

# --- WAF（4章）。ログは保存せず、サンプル表示と CloudWatch のメトリクスだけで見張る ---

# 全遮断：ふだんは空。全遮断のときは 0.0.0.0/1 と 128.0.0.0/1 を入れる（README の手順）。
# 手で入れた値を terraform apply が戻さないよう、addresses の変更は無視する
resource "aws_wafv2_ip_set" "block_all" {
  name               = "tkb_2613-block-all"
  description        = "Kill switch. Empty normally. Add 0.0.0.0/1 and 128.0.0.0/1 to block everyone."
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = []

  lifecycle {
    ignore_changes = [addresses]
  }
}

# OAuth 通し試験だけ有効にする。空ならルールを作らない
resource "aws_wafv2_ip_set" "oauth_test_allow" {
  name               = "tkb_2613-oauth-test-allow"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = var.oauth_test_ipv4_cidrs
}

resource "aws_wafv2_web_acl" "main" {
  name  = "tkb_2613"
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "kill-switch"
    priority = 0
    action {
      block {}
    }
    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.block_all.arn
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "kill-switch"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = length(var.oauth_test_ipv4_cidrs) > 0 ? [1] : []
    content {
      name     = "oauth-test-team-only"
      priority = 6
      action {
        block {}
      }
      statement {
        and_statement {
          statement {
            not_statement {
              statement {
                ip_set_reference_statement {
                  arn = aws_wafv2_ip_set.oauth_test_allow.arn
                }
              }
            }
          }
          # Bluesky の認可サーバーが取得するメタデータだけは公開する
          statement {
            not_statement {
              statement {
                byte_match_statement {
                  search_string         = "/oauth-client-metadata.json"
                  positional_constraint = "EXACTLY"
                  field_to_match {
                    uri_path {}
                  }
                  text_transformation {
                    priority = 0
                    type     = "URL_DECODE"
                  }
                  text_transformation {
                    priority = 1
                    type     = "NORMALIZE_PATH"
                  }
                  text_transformation {
                    priority = 2
                    type     = "LOWERCASE"
                  }
                }
              }
            }
          }
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "oauth-test-team-only"
        sampled_requests_enabled   = true
      }
    }
  }

  rule {
    name     = "ip-reputation"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  # 本番では 501 を返すだけの、ログイン不要の唯一の POST（検査 10）
  rule {
    name     = "block-detect"
    priority = 2
    action {
      block {}
    }
    statement {
      byte_match_statement {
        search_string         = "/api/detect"
        positional_constraint = "STARTS_WITH"
        field_to_match {
          uri_path {}
        }
        text_transformation {
          priority = 0
          type     = "URL_DECODE"
        }
        text_transformation {
          priority = 1
          type     = "NORMALIZE_PATH"
        }
        text_transformation {
          priority = 2
          type     = "LOWERCASE"
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "block-detect"
      sampled_requests_enabled   = true
    }
  }

  # ログインの総当たり（Bluesky のパスワードの踏み台）を止める（11章）
  rule {
    name     = "rate-login"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = var.rate_limit_login
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
        scope_down_statement {
          and_statement {
            statement {
              or_statement {
                statement {
                  byte_match_statement {
                    search_string         = "/api/session"
                    positional_constraint = "STARTS_WITH"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "URL_DECODE"
                    }
                    text_transformation {
                      priority = 1
                      type     = "NORMALIZE_PATH"
                    }
                    text_transformation {
                      priority = 2
                      type     = "LOWERCASE"
                    }
                  }
                }
                statement {
                  byte_match_statement {
                    search_string         = "/auth/start"
                    positional_constraint = "EXACTLY"
                    field_to_match {
                      uri_path {}
                    }
                    text_transformation {
                      priority = 0
                      type     = "URL_DECODE"
                    }
                    text_transformation {
                      priority = 1
                      type     = "NORMALIZE_PATH"
                    }
                    text_transformation {
                      priority = 2
                      type     = "LOWERCASE"
                    }
                  }
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = "POST"
                positional_constraint = "EXACTLY"
                field_to_match {
                  method {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-login"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-diagnose"
    priority = 4
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = var.rate_limit_diagnose
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
        scope_down_statement {
          byte_match_statement {
            search_string         = "/api/diagnose"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "URL_DECODE"
            }
            text_transformation {
              priority = 1
              type     = "NORMALIZE_PATH"
            }
            text_transformation {
              priority = 2
              type     = "LOWERCASE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-diagnose"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-all"
    priority = 5
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit                 = var.rate_limit_all
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
        # Next.js の静的ファイルは数えない（1回ページを開くと数十件になり、会場や大学のように
        # 1つの IP から大勢が来ると、すぐ上限に届くため）
        scope_down_statement {
          not_statement {
            statement {
              byte_match_statement {
                search_string         = "/_next/static/"
                positional_constraint = "STARTS_WITH"
                field_to_match {
                  uri_path {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-all"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "tkb_2613"
    sampled_requests_enabled   = true
  }
}
