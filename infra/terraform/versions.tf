terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # CloudFront VPC origin（aws_cloudfront_vpc_origin）は 5.82 から
      version = ">= 5.82, < 7.0"
    }
  }

  # state はローカル（内藤の PC）に置く。.gitignore で除外し、apply のたびにリポジトリの外へコピーする（README）
}

provider "aws" {
  region = var.region

  # すべてのリソースに Project=tkb_2613 を付ける（消し忘れを Cost Explorer とタグで確かめる）
  default_tags {
    tags = {
      Project = "tkb_2613"
    }
  }
}
