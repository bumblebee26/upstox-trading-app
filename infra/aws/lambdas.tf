# The code all three Lambdas run (kicker, responder, guardian): this repo's core/, trader/ (without the MCP
# server, which needs the session's libraries) and lambdas/. AWS's Python runtime already has boto3.
locals {
  repo_root = "${path.module}/../.."
  app_files = setunion(
    fileset(local.repo_root, "core/*.py"),
    [for f in fileset(local.repo_root, "trader/*.py") : f if f != "trader/server.py"],
    fileset(local.repo_root, "lambdas/*.py"),
  )
  # name => [schedule in India time, timeout in seconds, what it does]
  ops = {
    responder = ["rate(1 minute)", 55, "answers Telegram while no trading session runs"]
    guardian  = ["cron(*/5 9-15 ? * MON-FRI *)", 120, "alerts on a silent session; closes what a dead one left open"]
  }
}

data "archive_file" "app" {
  type        = "zip"
  output_path = "${path.module}/build/app.zip"

  dynamic "source" {
    for_each = local.app_files
    content {
      content  = file("${local.repo_root}/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "ops" {
  #checkov:skip=CKV_AWS_158:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; logs are encrypted by AWS
  for_each          = local.ops
  name              = "/aws/lambda/upx-${each.key}"
  retention_in_days = 365
}

resource "aws_iam_role" "ops" {
  name                 = "upx-ops-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = local.boundary
}

# The responder and guardian read and write the intraday state, journal, feed and their own notes, read the
# session claims, and read the Upstox and Telegram secrets. Nothing else.
data "aws_iam_policy_document" "ops" {
  statement {
    sid       = "ListStateSoMissingKeysReadAsMissing"
    actions   = ["s3:ListBucket"]
    resources = [module.state_bucket.arn]
  }
  statement {
    sid       = "ReadState"
    actions   = ["s3:GetObject"]
    resources = ["${module.state_bucket.arn}/*"]
  }
  statement {
    sid       = "WriteStateJournalFeedNotes"
    actions   = ["s3:PutObject"]
    resources = [for k in ["state", "journal", "feed", "guardian"] : "${module.state_bucket.arn}/${k}/*"]
  }
  statement {
    sid     = "ReadOwnSecrets"
    actions = ["ssm:GetParameter"]
    resources = [for p in ["upstox-analytics-token", "telegram-bot-token-v2", "telegram-chat-id"] :
    "arn:aws:ssm:ap-southeast-2:${local.account_id}:parameter/upx/${p}"]
  }
  statement {
    sid       = "DecryptViaSsm"
    actions   = ["kms:Decrypt"]
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
    resources = [for g in aws_cloudwatch_log_group.ops : "${g.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ops" {
  name   = "upx-ops"
  role   = aws_iam_role.ops.id
  policy = data.aws_iam_policy_document.ops.json
}

resource "aws_lambda_function" "ops" {
  #checkov:skip=CKV_AWS_116:a dead-letter queue needs SQS, not on the AWS free plan; the next scheduled run tries again
  #checkov:skip=CKV_AWS_117:it only calls Upstox, Telegram and S3; a VPC would need a NAT gateway (about $35 a month)
  #checkov:skip=CKV_AWS_115:a new account shares 10 concurrent runs, so reserving some can fail
  #checkov:skip=CKV_AWS_272:code signing needs AWS Signer, not on the AWS free plan; code comes only from this repo via reviewed merges
  #checkov:skip=CKV_AWS_50:X-Ray is not on the AWS free plan
  #checkov:skip=CKV_AWS_173:owner OK 27 Nov (free plan only): the settings hold only the bucket name, no secret; AWS encrypts them with its own key
  for_each         = local.ops
  function_name    = "upx-${each.key}"
  description      = each.value[2]
  role             = aws_iam_role.ops.arn
  runtime          = "python3.13"
  handler          = "lambdas.${each.key}.handler"
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256
  timeout          = each.value[1]
  memory_size      = 256
  depends_on       = [aws_cloudwatch_log_group.ops]

  environment {
    variables = { UPX_STATE_BUCKET = module.state_bucket.id, UPX_DATA_DIR = "/tmp/upx" }
  }
}

resource "aws_scheduler_schedule" "ops" {
  #checkov:skip=CKV_AWS_297:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; AWS encrypts schedules
  for_each                     = local.ops
  name                         = "upx-${each.key}"
  schedule_expression          = each.value[0]
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.ops[each.key].arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy { # the next run comes soon anyway; a late copy would only race it
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60
    }
  }
}
