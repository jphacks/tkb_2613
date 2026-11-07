data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# NVIDIA のドライバと Docker・NVIDIA Container Toolkit・AWS CLI が入った AMI
data "aws_ssm_parameter" "dlami" {
  name = "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.app_instance_type
  subnet_id              = aws_subnet.app.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.instance["app"].name

  associate_public_ip_address = false

  # IMDSv2 必須。hop limit 1 なので、コンテナからはインスタンスの認証情報に届かない
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/app-user-data.sh.tftpl", {
    region          = var.region
    secret_id       = aws_secretsmanager_secret.vlm_api_key.name
    repo_url        = var.repo_url
    repo_ref        = var.repo_ref
    compose_version = var.compose_version
    buildx_version  = var.buildx_version
  })
  # user_data を変えても作り直さない（作り直すと手で作った .env が消える）
  user_data_replace_on_change = false

  tags = { Name = "tkb_2613-app", Role = "app" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_instance" "gpu" {
  ami                    = data.aws_ssm_parameter.dlami.value
  instance_type          = var.gpu_instance_type
  subnet_id              = aws_subnet.gpu.id
  private_ip             = var.gpu_private_ip
  vpc_security_group_ids = [aws_security_group.gpu.id]
  iam_instance_profile   = aws_iam_instance_profile.instance["gpu"].name

  associate_public_ip_address = false

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.gpu_root_volume_gb
    encrypted   = true
  }

  user_data = templatefile("${path.module}/templates/gpu-user-data.sh.tftpl", {
    region             = var.region
    secret_id          = aws_secretsmanager_secret.vlm_api_key.name
    vllm_image         = var.vllm_image
    vlm_model          = var.vlm_model
    vlm_served_name    = var.vlm_served_name
    gpu_memory_util    = var.vllm_gpu_memory_utilization
    ocr_image          = var.ocr_image
    ocr_container_port = var.ocr_container_port
  })
  user_data_replace_on_change = false

  # 停止はスケジュールと Budgets action と予備の担当が行う。Role=gpu のタグで権限を絞っている
  tags = { Name = "tkb_2613-gpu", Role = "gpu" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
