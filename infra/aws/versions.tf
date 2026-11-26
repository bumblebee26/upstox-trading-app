terraform {
  # 1.10+ for S3-native state locking (use_lockfile).
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # This repo's own state bucket (made by infra/bootstrap). Never the old repos' state bucket.
  backend "s3" {
    bucket       = "upx-tfstate-538498973473"
    key          = "aws/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
