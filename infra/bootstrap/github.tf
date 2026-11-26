# How GitHub Actions signs in to AWS for Terraform, without a stored key (applied by the owner from their PC,
# like the state bucket; CI can never change this file's resources).
#   upx-gha-plan   read-only, for "terraform plan" on pull requests
#   upx-gha-apply  makes changes, only from the "infra" environment (the owner clicks Approve on each run)
#   upx-boundary   the most any upx- role or user may ever do; the apply role can create or change upx-
#                  roles only with this limit attached, so it can't hand anything more power than this
locals {
  account_id = data.aws_caller_identity.me.account_id
  repo       = "bumblebee26/upstox-trading-app"
  boundary   = "arn:aws:iam::${local.account_id}:policy/upx-boundary"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# ---- The ceiling for every upx- role and user ------------------------------------------------------------------
data "aws_iam_policy_document" "boundary" {
  statement {
    sid       = "OwnBuckets"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::upx-*", "arn:aws:s3:::upx-*/*"]
  }
  statement {
    sid       = "OwnParameters"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:PutParameter"]
    resources = ["arn:aws:ssm:ap-southeast-2:${local.account_id}:parameter/upx/*"]
  }
  statement {
    sid       = "DecryptViaSsm"
    actions   = ["kms:Decrypt", "kms:Encrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.ap-southeast-2.amazonaws.com"]
    }
  }
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:ap-southeast-2:${local.account_id}:log-group:/aws/lambda/upx-*"]
  }
  statement {
    sid       = "OwnLambdas"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:ap-southeast-2:${local.account_id}:function:upx-*"]
  }
}

resource "aws_iam_policy" "boundary" {
  name   = "upx-boundary"
  policy = data.aws_iam_policy_document.boundary.json
}

# ---- Who may use each role -------------------------------------------------------------------------------------
data "aws_iam_policy_document" "trust" {
  for_each = { plan = "pull_request", apply = "environment:infra" }
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.repo}:${each.value}"]
    }
  }
}

# ---- Plan: read only -------------------------------------------------------------------------------------------
data "aws_iam_policy_document" "plan" {
  statement {
    sid = "ReadBuckets"
    actions = ["s3:ListBucket", "s3:GetBucket*", "s3:GetAccelerateConfiguration", "s3:GetEncryptionConfiguration",
    "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration"]
    resources = ["arn:aws:s3:::upx-*"]
  }
  statement {
    sid       = "ReadTerraformState" # plan runs with -lock=false, so it never writes the lock file
    actions   = ["s3:GetObject"]
    resources = ["${module.state_bucket.arn}/aws/terraform.tfstate"]
  }
  statement {
    sid = "ReadOwnResources"
    actions = ["iam:Get*", "iam:List*", "lambda:GetFunction*", "lambda:GetPolicy", "lambda:ListVersionsByFunction",
      "lambda:ListTags", "lambda:GetRuntimeManagementConfig", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
    "scheduler:GetSchedule", "scheduler:ListTagsForResource"]
    resources = [
      "arn:aws:iam::${local.account_id}:role/upx-*",
      "arn:aws:iam::${local.account_id}:user/upx-*",
      "arn:aws:iam::${local.account_id}:policy/upx-*",
      "arn:aws:lambda:ap-southeast-2:${local.account_id}:function:upx-*",
      "arn:aws:logs:ap-southeast-2:${local.account_id}:log-group:/aws/lambda/upx-*",
      "arn:aws:scheduler:ap-southeast-2:${local.account_id}:schedule/default/upx-*",
    ]
  }
  statement {
    sid       = "ListCallsThatTakeNoResource"
    actions   = ["logs:DescribeLogGroups", "scheduler:ListSchedules"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "plan" {
  name                 = "upx-gha-plan"
  assume_role_policy   = data.aws_iam_policy_document.trust["plan"].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "plan" {
  name   = "upx-gha-plan"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}

# ---- Apply: changes, inside limits -----------------------------------------------------------------------------
data "aws_iam_policy_document" "apply" {
  source_policy_documents = [data.aws_iam_policy_document.plan.json]
  statement {
    sid       = "ManageOwnBuckets"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::upx-*"]
  }
  statement {
    sid       = "TerraformStateAndLock"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${module.state_bucket.arn}/aws/*"]
  }
  statement {
    sid       = "ManageOwnLambdasLogsSchedules"
    actions   = ["lambda:*", "logs:*", "scheduler:*"]
    resources = [
      "arn:aws:lambda:ap-southeast-2:${local.account_id}:function:upx-*",
      "arn:aws:logs:ap-southeast-2:${local.account_id}:log-group:/aws/lambda/upx-*",
      "arn:aws:logs:ap-southeast-2:${local.account_id}:log-group:/aws/lambda/upx-*:*",
      "arn:aws:scheduler:ap-southeast-2:${local.account_id}:schedule/default/upx-*",
    ]
  }
  statement {
    sid       = "ChangeRolesAndUsersOnlyWithTheBoundary"
    actions = ["iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy",
      "iam:DetachRolePolicy", "iam:PutRolePermissionsBoundary", "iam:CreateUser", "iam:PutUserPolicy",
    "iam:DeleteUserPolicy", "iam:AttachUserPolicy", "iam:DetachUserPolicy", "iam:PutUserPermissionsBoundary"]
    resources = ["arn:aws:iam::${local.account_id}:role/upx-*", "arn:aws:iam::${local.account_id}:user/upx-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary]
    }
  }
  statement {
    sid = "OtherRoleAndUserChanges"
    actions = ["iam:DeleteRole", "iam:UpdateRole", "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole",
    "iam:DeleteUser", "iam:TagUser", "iam:UntagUser"]
    resources = ["arn:aws:iam::${local.account_id}:role/upx-*", "arn:aws:iam::${local.account_id}:user/upx-*"]
  }
  statement {
    sid       = "PassOwnRolesToLambdaAndScheduler"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/upx-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com", "scheduler.amazonaws.com"]
    }
  }
  statement {
    sid    = "NeverTouchTheseOrMakeKeys"
    effect = "Deny"
    actions = ["iam:*"]
    resources = [aws_iam_role.plan.arn, "arn:aws:iam::${local.account_id}:role/upx-gha-apply", local.boundary,
    aws_iam_openid_connect_provider.github.arn]
  }
  statement {
    sid    = "NoKeysPasswordsOrBoundaryRemoval"
    effect = "Deny"
    actions = ["iam:CreateAccessKey", "iam:UpdateAccessKey", "iam:CreateLoginProfile", "iam:UpdateLoginProfile",
    "iam:DeleteRolePermissionsBoundary", "iam:DeleteUserPermissionsBoundary"]
    resources = ["*"]
  }
  statement {
    sid       = "NeverDeleteTheBuckets"
    effect    = "Deny"
    actions   = ["s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:PutBucketVersioning"]
    resources = ["arn:aws:s3:::upx-*"]
  }
}

resource "aws_iam_role" "apply" {
  name                 = "upx-gha-apply"
  assume_role_policy   = data.aws_iam_policy_document.trust["apply"].json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "apply" {
  name   = "upx-gha-apply"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.apply.json
}

output "plan_role" {
  value = aws_iam_role.plan.arn
}

output "apply_role" {
  value = aws_iam_role.apply.arn
}
