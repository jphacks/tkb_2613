# 予算 $100：$50 でメール、$80 で GPU を自動で止める（6章）。
# 請求の集計は数時間〜1日遅れるので、これは最後の安全網。ふだんは公開時間帯のスケジュールで止める

resource "aws_budgets_budget" "main" {
  name         = "tkb_2613"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_notify_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_limit_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "budgets_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
    # 自分のアカウントの Budgets からだけ引き受けられる（混乱した代理人の対策）
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "budgets_action" {
  name               = "tkb_2613-budgets-action"
  assume_role_policy = data.aws_iam_policy_document.budgets_assume.json
}

resource "aws_iam_role_policy_attachment" "budgets_action" {
  role       = aws_iam_role.budgets_action.name
  policy_arn = "arn:aws:iam::aws:policy/AWSBudgetsActions_RolePolicyForResourceAdministrationWithSSM"
}

resource "aws_budgets_budget_action" "stop_gpu" {
  budget_name        = aws_budgets_budget.main.name
  action_type        = "RUN_SSM_DOCUMENTS"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budgets_action.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = var.budget_stop_gpu_usd
  }

  definition {
    ssm_action_definition {
      action_sub_type = "STOP_EC2_INSTANCES"
      instance_ids    = [aws_instance.gpu.id]
      region          = var.region
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }
}

# GPU を止めても、次の公開時間帯のスケジュールがまた起動してしまう。$80 を超えたら、スケジュールの
# ロールに「起動を禁止する」ポリシーを付けて、再開しないようにする（再開するときは README の手順で外す）
data "aws_iam_policy_document" "deny_gpu_start" {
  statement {
    effect    = "Deny"
    actions   = ["ec2:StartInstances"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "deny_gpu_start" {
  name        = "tkb_2613-deny-gpu-start"
  description = "Attached by the Budgets action at the stop threshold so the schedules cannot restart the GPU"
  policy      = data.aws_iam_policy_document.deny_gpu_start.json
}

data "aws_iam_policy_document" "budgets_attach_deny" {
  statement {
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = [aws_iam_role.scheduler.arn]
    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [aws_iam_policy.deny_gpu_start.arn]
    }
  }
}

resource "aws_iam_role_policy" "budgets_attach_deny" {
  name   = "attach-deny-gpu-start"
  role   = aws_iam_role.budgets_action.name
  policy = data.aws_iam_policy_document.budgets_attach_deny.json
}

resource "aws_budgets_budget_action" "block_gpu_restart" {
  budget_name        = aws_budgets_budget.main.name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budgets_action.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = var.budget_stop_gpu_usd
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.deny_gpu_start.arn
      roles      = [aws_iam_role.scheduler.name]
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }
}

