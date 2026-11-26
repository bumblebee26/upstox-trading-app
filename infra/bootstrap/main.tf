# Run once by the owner, from their PC: creates the bucket that holds this repo's Terraform state.
# Its own state stays on the PC (terraform.tfstate here, not committed); the bucket is protected from deletion.
#   cd infra/bootstrap
#   terraform init
#   terraform apply
terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-2"
  default_tags {
    tags = { project = "upstox-trading-app" }
  }
}

data "aws_caller_identity" "me" {}

module "state_bucket" {
  source      = "../modules/secure_bucket"
  bucket_name = "upx-tfstate-${data.aws_caller_identity.me.account_id}"
}

output "state_bucket" {
  value = module.state_bucket.id
}
