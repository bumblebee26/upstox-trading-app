# The kicker: EventBridge Scheduler calls a small Lambda at fixed India times, and the Lambda starts a GitHub
# workflow. GitHub's own cron can run hours late; it stays in the workflows only as a backup.

resource "aws_cloudwatch_log_group" "kicker" {
  #checkov:skip=CKV_AWS_158:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; logs are encrypted by AWS
  name              = "/aws/lambda/upx-kicker"
  retention_in_days = 365
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "kicker" {
  name                 = "upx-kicker-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = local.boundary
}

# The kicker may read the GitHub dispatch token and the Telegram bot (to report a failed start), save that
# message to the app's feed, and write its own logs.
data "aws_iam_policy_document" "kicker" {
  statement {
    sid       = "ReadDispatchToken"
    actions   = ["ssm:GetParameter"]
    resources = [for p in ["github-dispatch-token", "telegram-bot-token-v2", "telegram-chat-id"] :
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
    resources = ["${aws_cloudwatch_log_group.kicker.arn}:*"]
  }
  statement {
    sid       = "WriteTheFeed"
    actions   = ["s3:PutObject"]
    resources = ["${module.state_bucket.arn}/feed/*"]
  }
}

resource "aws_iam_role_policy" "kicker" {
  name   = "upx-kicker"
  role   = aws_iam_role.kicker.id
  policy = data.aws_iam_policy_document.kicker.json
}

resource "aws_lambda_function" "kicker" {
  #checkov:skip=CKV_AWS_116:a dead-letter queue needs SQS, not on the AWS free plan; failures are alerted by Telegram (PR 9b)
  #checkov:skip=CKV_AWS_117:it only calls GitHub; a VPC would need a NAT gateway (about $35 a month)
  #checkov:skip=CKV_AWS_115:a new account shares 10 concurrent runs, so reserving some can fail; schedules start at most one at a time
  #checkov:skip=CKV_AWS_272:code signing needs AWS Signer, not on the AWS free plan; code comes only from this repo via reviewed merges
  #checkov:skip=CKV_AWS_50:X-Ray is not on the AWS free plan
  function_name    = "upx-kicker"
  role             = aws_iam_role.kicker.arn
  runtime          = "python3.13"
  handler          = "lambdas.kicker.handler"
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256
  timeout          = 30
  memory_size      = 128
  depends_on       = [aws_cloudwatch_log_group.kicker]

  environment {
    variables = { UPX_STATE_BUCKET = module.state_bucket.id }
  }
}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name                 = "upx-scheduler-role"
  assume_role_policy   = data.aws_iam_policy_document.scheduler_trust.json
  permissions_boundary = local.boundary
}

resource "aws_iam_role_policy" "scheduler" {
  name = "upx-scheduler"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = concat([aws_lambda_function.kicker.arn], [for f in aws_lambda_function.ops : f.arn])
    }]
  })
}

locals {
  # name => [cron in India time, workflow, inputs]. Holidays are handled by the session itself.
  kicks = {
    "upx-morning-session"   = ["cron(58 8 ? * MON-FRI *)", "trading-session.yml", { phase = "morning" }]
    "upx-afternoon-session" = ["cron(27 12 ? * MON-FRI *)", "trading-session.yml", { phase = "afternoon" }]
    "upx-pools-daily"       = ["cron(50 15 ? * MON-FRI *)", "pools.yml", { pools = "swing long_term" }]
    "upx-long-term-weekly"  = ["cron(15 10 ? * SAT *)", "pools.yml", { pools = "long_term" }]
    "upx-shadows-daily"     = ["cron(10 16 ? * MON-FRI *)", "shadows.yml", {}]
  }
}

resource "aws_scheduler_schedule" "kick" {
  #checkov:skip=CKV_AWS_297:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; AWS encrypts schedules
  for_each                     = local.kicks
  name                         = each.key
  schedule_expression          = each.value[0]
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.kicker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ workflow = each.value[1], inputs = each.value[2] })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
