# 公開時間帯に合わせて GPU を起動・停止する（6.3）。時刻は日本時間の1回だけの予定

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler_gpu" {
  statement {
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = [aws_instance.gpu.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "tkb_2613-gpu-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "start-stop-gpu"
  role   = aws_iam_role.scheduler.name
  policy = data.aws_iam_policy_document.scheduler_gpu.json
}

locals {
  gpu_schedules = merge([
    for w in var.public_windows : {
      "start-${w.date}" = { at = "${w.date}T${w.gpu_start}:00", action = "startInstances" }
      "stop-${w.date}"  = { at = "${w.date}T${w.gpu_stop}:00", action = "stopInstances" }
    }
  ]...)
}

resource "aws_scheduler_schedule" "gpu" {
  for_each = local.gpu_schedules

  name                         = "tkb_2613-gpu-${each.key}"
  schedule_expression          = "at(${each.value.at})"
  schedule_expression_timezone = "Asia/Tokyo"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:${each.value.action}"
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ InstanceIds = [aws_instance.gpu.id] })
  }
}
