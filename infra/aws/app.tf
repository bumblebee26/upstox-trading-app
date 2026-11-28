# The phone app: a private bucket, and a small Lambda that serves it at a secret address (CloudFront is not on
# the AWS free plan). The page comes from app/ in this repo; its data comes from the Lakehouse job's export
# (appdata/export.py), which writes app/data/*.json and keeps a daily copy of the market values under history/.

# A random path, made once (uuid() is random; ignore_changes keeps the first one).
resource "terraform_data" "app_path" {
  input = uuid()

  lifecycle {
    ignore_changes = [input]
  }
}

locals {
  app_path = terraform_data.app_path.output
  # The app's own files, uploaded on each apply (the page arrives in B1b).
  app_pages = {
    for f in try(fileset("${local.repo_root}/app", "{index.html,manifest.webmanifest,icon.svg}"), []) : f => lookup({
      "index.html"           = "text/html; charset=utf-8"
      "manifest.webmanifest" = "application/manifest+json"
      "icon.svg"             = "image/svg+xml"
    }, f, "application/octet-stream")
  }
}

module "app_bucket" {
  source                 = "../modules/secure_bucket"
  bucket_name            = "upx-app-${local.account_id}"
  keep_old_versions_days = 7
}

resource "aws_s3_object" "app_pages" {
  for_each      = local.app_pages
  bucket        = module.app_bucket.id
  key           = "app/${each.key}"
  source        = "${local.repo_root}/app/${each.key}"
  etag          = filemd5("${local.repo_root}/app/${each.key}")
  content_type  = each.value
  cache_control = "max-age=300"
}

resource "aws_cloudwatch_log_group" "app_web" {
  #checkov:skip=CKV_AWS_158:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; logs are encrypted by AWS
  name              = "/aws/lambda/upx-app-web"
  retention_in_days = 365
}

resource "aws_iam_role" "app_web" {
  name                 = "upx-app-web-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = local.boundary
}

data "aws_iam_policy_document" "app_web" {
  statement {
    sid       = "ReadAppFilesOnly"
    actions   = ["s3:GetObject"]
    resources = ["${module.app_bucket.arn}/app/*"]
  }
  statement {
    sid       = "OwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app_web.arn}:*"]
  }
}

resource "aws_iam_role_policy" "app_web" {
  name   = "upx-app-web"
  role   = aws_iam_role.app_web.id
  policy = data.aws_iam_policy_document.app_web.json
}

resource "aws_lambda_function" "app_web" {
  #checkov:skip=CKV_AWS_116:a dead-letter queue needs SQS, not on the AWS free plan; a phone simply reloads
  #checkov:skip=CKV_AWS_117:it only reads its own bucket; a VPC would need a NAT gateway (about $35 a month)
  #checkov:skip=CKV_AWS_115:a new account shares 10 concurrent runs, so reserving some can fail
  #checkov:skip=CKV_AWS_272:code signing needs AWS Signer, not on the AWS free plan; code comes only from this repo via reviewed merges
  #checkov:skip=CKV_AWS_50:X-Ray is not on the AWS free plan
  #checkov:skip=CKV_AWS_173:owner OK 27 Nov (free plan only): the settings hold the bucket name and the app's path; AWS encrypts them with its own key
  function_name    = "upx-app-web"
  description      = "Phone app: serves /<secret path>/<app file> from the private bucket; 404 otherwise"
  role             = aws_iam_role.app_web.arn
  runtime          = "python3.13"
  handler          = "lambdas.app_web.handler"
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256
  timeout          = 10
  memory_size      = 128
  depends_on       = [aws_cloudwatch_log_group.app_web]

  environment {
    variables = { APP_BUCKET = module.app_bucket.id, APP_PATH = local.app_path }
  }
}

resource "aws_lambda_function_url" "app_web" {
  #checkov:skip=CKV_AWS_258:a phone can't sign requests; only the secret path is served (lambdas/app_web.py)
  function_name      = aws_lambda_function.app_web.function_name
  authorization_type = "NONE"
}

# A public function URL needs both permissions (AWS, Oct 2025); InvokeFunction only for calls through the URL.
resource "aws_lambda_permission" "app_web_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.app_web.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "app_web_invoke" {
  statement_id             = "FunctionURLInvokeAllowPublicAccess"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.app_web.function_name
  principal                = "*"
  invoked_via_function_url = true
}

# The app's link, for the owner: aws ssm get-parameter --name /upx/app-url --with-decryption
resource "aws_ssm_parameter" "app_url" {
  #checkov:skip=CKV_AWS_337:a customer-managed KMS key costs $1 a month and KMS is not on the AWS free plan; SecureString uses the AWS key
  name        = "/upx/app-url"
  description = "The phone app's link (address + secret path). Anyone with it can open the app."
  type        = "SecureString"
  value       = "${trimsuffix(aws_lambda_function_url.app_web.function_url, "/")}/${local.app_path}/"
}

output "app_bucket" {
  value = module.app_bucket.id
}
