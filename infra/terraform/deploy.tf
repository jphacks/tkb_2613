# GitHub Actions の「本番デプロイ」（.github/workflows/deploy.yml）から、最新の main をアプリの EC2 に出す。
#
# - 認証は GitHub の OIDC。main ブランチで動くジョブだけがロールを引き受けられる（長期のキーを持たない）
# - できることは、このドキュメントをアプリの EC2 に送ることと、その結果を読むことだけ。
#   任意のシェルは送れない（AWS-RunShellScript は許さない）。GPU の EC2 には何もできない
# - ドキュメントは、コミット SHA（40桁の16進）だけを受け取り、そのコミットの infra/deploy.sh を実行する。
#   deploy.sh は、それが origin/main の最新でなければ何もせずに止まる

variable "github_repository" {
  description = "デプロイを許す GitHub のリポジトリ（owner/name）"
  type        = string
  default     = "jphacks/tkb_2613"
}

# GitHub の OIDC プロバイダはアカウントに1つだけ作れる。Terraform の外で作ってあるので、参照だけする
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_ssm_document" "deploy" {
  name            = "tkb_2613-deploy"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "最新の main（指定した SHA）を infra/deploy.sh で本番に出す。失敗したら前のコミットに戻す"
    parameters = {
      CommitSha = {
        type           = "String"
        description    = "デプロイする main のコミット（40桁の小文字16進）"
        allowedPattern = "^[0-9a-f]{40}$"
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = {
        timeoutSeconds = "1800"
        runCommand = [
          "set -euo pipefail",
          "cd /opt/tkb_2613",
          "git fetch --quiet origin main",
          # 実行するのは、デプロイするコミット（レビュー済みの main）の deploy.sh。いまの checkout の版ではない
          "git show '{{ CommitSha }}:infra/deploy.sh' > /run/tkb_2613-deploy.sh",
          "chmod 700 /run/tkb_2613-deploy.sh",
          "trap 'rm -f /run/tkb_2613-deploy.sh' EXIT",
          "/run/tkb_2613-deploy.sh '{{ CommitSha }}'",
        ]
      }
    }]
  })
}

data "aws_iam_policy_document" "github_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # main ブランチで動いたジョブだけ（PR・ほかのブランチ・fork からは引き受けられない）
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "tkb_2613-github-deploy"
  description          = "GitHub Actions の本番デプロイ。SSM ドキュメント tkb_2613-deploy をアプリの EC2 に送るだけ"
  assume_role_policy   = data.aws_iam_policy_document.github_deploy_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid     = "SendDeployDocumentToAppOnly"
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.app.arn,
      aws_ssm_document.deploy.arn,
    ]
  }

  statement {
    sid = "ReadCommandResults"
    # 結果の読み取りは対象を絞れない（読むだけ）
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "send-deploy-document"
  role   = aws_iam_role.github_deploy.name
  policy = data.aws_iam_policy_document.github_deploy.json
}
