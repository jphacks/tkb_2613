data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# アプリと GPU のインスタンスロール：SSM で入れることと、VLM のキーを読むことだけ
data "aws_iam_policy_document" "read_vlm_key" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.vlm_api_key.arn]
  }
}

resource "aws_iam_role" "instance" {
  for_each           = toset(["app", "gpu"])
  name               = "tkb_2613-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  for_each   = aws_iam_role.instance
  role       = each.value.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "read_vlm_key" {
  for_each = aws_iam_role.instance
  name     = "read-vlm-key"
  role     = each.value.name
  policy   = data.aws_iam_policy_document.read_vlm_key.json
}

resource "aws_iam_instance_profile" "instance" {
  for_each = aws_iam_role.instance
  name     = "tkb_2613-${each.key}"
  role     = each.value.name
}

# --- 全遮断の予備の担当（谷口）：WAF の全遮断の IP セットの切り替えと、タグ付きの GPU の停止だけ ---

resource "aws_iam_user" "killswitch" {
  name = var.killswitch_user_name
  # アクセスキーは Terraform で作らない（state に入れない）。README の手順でコンソールから発行して渡す
}

data "aws_iam_policy_document" "killswitch" {
  statement {
    sid       = "ToggleBlockAll"
    actions   = ["wafv2:GetIPSet", "wafv2:UpdateIPSet"]
    resources = [aws_wafv2_ip_set.block_all.arn]
  }

  statement {
    sid       = "FindTheIpSet"
    actions   = ["wafv2:ListIPSets"]
    resources = ["*"] # 一覧は対象を絞れない（読み取りだけ）
  }

  statement {
    sid       = "StopTaggedGpu"
    actions   = ["ec2:StopInstances"]
    resources = ["arn:aws:ec2:${var.region}:*:instance/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = ["tkb_2613"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Role"
      values   = ["gpu"]
    }
  }

  statement {
    sid       = "FindTheGpu"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"] # Describe は対象を絞れない（読み取りだけ）
  }
}

resource "aws_iam_user_policy" "killswitch" {
  name   = "killswitch-only"
  user   = aws_iam_user.killswitch.name
  policy = data.aws_iam_policy_document.killswitch.json
}
