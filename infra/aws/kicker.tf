# The kicker: EventBridge Scheduler calls a small Lambda at fixed India times, and the Lambda starts a GitHub
# workflow. GitHub's own cron can run hours late; it stays in the workflows only as a backup.

data "archive_file" "kicker" {
  type        = "zip"
  output_path = "${path.module}/build/kicker.zip"

  source {
    content  = ""
    filename = "core/__init__.py"
  }
  source {
    content  = file("${path.module}/../../core/http.py")
    filename = "core/http.py"
  }
  source {
    content  = file("${path.module}/../../core/ssm.py")
    filename = "core/ssm.py"
  }
  source {
    content  = ""
    filename = "lambdas/__init__.py"
  }
  source {
    content  = file("${path.module}/../../lambdas/kicker.py")
    filename = "lambdas/kicker.py"
  }
}

resource "aws_cloudwatch_log_group" "kicker" {
  name              = "/aws/lambda/upx-kicker"
  retention_in_days = 14
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
  name               = "upx-kicker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

# The kicker may read only the GitHub dispatch token and write its own logs.
data "aws_iam_policy_document" "kicker" {
  statement {
    sid       = "ReadDispatchToken"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:ap-southeast-2:${local.account_id}:parameter/upx/github-dispatch-token"]
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
}

resource "aws_iam_role_policy" "kicker" {
  name   = "upx-kicker"
  role   = aws_iam_role.kicker.id
  policy = data.aws_iam_policy_document.kicker.json
}

resource "aws_lambda_function" "kicker" {
  function_name    = "upx-kicker"
  role             = aws_iam_role.kicker.arn
  runtime          = "python3.13"
  handler          = "lambdas.kicker.handler"
  filename         = data.archive_file.kicker.output_path
  source_code_hash = data.archive_file.kicker.output_base64sha256
  timeout          = 30
  memory_size      = 128
  depends_on       = [aws_cloudwatch_log_group.kicker]
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
  name               = "upx-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "upx-scheduler"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.kicker.arn }]
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
