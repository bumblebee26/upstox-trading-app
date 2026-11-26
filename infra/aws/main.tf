# AWS resources for the trader. Applied by the owner from their PC until PR 9 adds plan/apply in CI:
#   cd infra/aws
#   terraform init
#   terraform apply
provider "aws" {
  region = "ap-southeast-2"
  default_tags {
    tags = { project = "upstox-trading-app" }
  }
}

data "aws_caller_identity" "me" {}

locals {
  account_id = data.aws_caller_identity.me.account_id
}

# Ledgers, journals, plans, the instrument file and the Telegram feed.
module "state_bucket" {
  source      = "../modules/secure_bucket"
  bucket_name = "upx-state-${local.account_id}"
}

# The GitHub Actions trading session signs in as this user (the AWS free plan has no GitHub OIDC).
# Its access key is created by the owner outside Terraform, so the secret never sits in Terraform state.
resource "aws_iam_user" "session" {
  name = "upx-gha-trader"
}

data "aws_iam_policy_document" "session" {
  statement {
    sid       = "ListState"
    actions   = ["s3:ListBucket"]
    resources = [module.state_bucket.arn]
  }
  statement {
    sid       = "ReadWriteStateNoDelete"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${module.state_bucket.arn}/*"]
  }
  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = ["arn:aws:ssm:ap-southeast-2:${local.account_id}:parameter/upx/*"]
  }
  statement {
    sid       = "DecryptOwnSecretsViaSsm"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.ap-southeast-2.amazonaws.com"]
    }
  }
}

resource "aws_iam_user_policy" "session" {
  name   = "upx-gha-trader"
  user   = aws_iam_user.session.name
  policy = data.aws_iam_policy_document.session.json
}

output "state_bucket" {
  value = module.state_bucket.id
}

output "session_user" {
  value = aws_iam_user.session.name
}
