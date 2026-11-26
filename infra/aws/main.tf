# AWS resources for the trader. Planned on every pull request and applied by GitHub Actions after a merge to main,
# once the owner clicks Approve in the "infra" environment (.github/workflows/terraform.yml). The owner can still
# apply from their PC:
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
  boundary   = "arn:aws:iam::${local.account_id}:policy/upx-boundary" # made by infra/bootstrap/github.tf
}

# Ledgers, journals, plans, the instrument file and the Telegram feed.
module "state_bucket" {
  source      = "../modules/secure_bucket"
  bucket_name = "upx-state-${local.account_id}"
}

# The GitHub Actions trading session signs in as this user, with an access key the owner created outside
# Terraform, so the secret never sits in Terraform state.
resource "aws_iam_user" "session" {
  #checkov:skip=CKV_AWS_273:owner's choice (27 Nov): the session keeps its working access key; a role can replace it later
  name                 = "upx-gha-trader"
  permissions_boundary = local.boundary
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
  #checkov:skip=CKV_AWS_40:the one user above keeps its own policy until a role replaces it
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
