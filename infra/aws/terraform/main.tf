terraform {
  required_version = ">= 1.5"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.70" }
    archive = { source = "hashicorp/archive", version = "~> 2.6" }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "careplan-coursework" }
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "llm_model" {
  type        = string
  description = "Available Claude model ID; explicitly set for your account."
}

variable "anthropic_base_url" {
  type    = string
  default = "https://api.anthropic.com"
}

variable "max_attempts" {
  type    = number
  default = 3
}

# ---------------- Database: DynamoDB (single table) ----------------
# pk = "ORDER#<uuid>" for orders, "DUP#<mrn>#<drug>#<date>" for the same-day duplicate guard (expires via TTL).
resource "aws_dynamodb_table" "orders" {
  name         = "careplan-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# ---------------- Queue + Dead Letter Queue ----------------
resource "aws_sqs_queue" "dlq" {
  name                      = "careplan-jobs-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "jobs" {
  name                       = "careplan-jobs"
  visibility_timeout_seconds = 720 # Six times the worker timeout for SQS throttling/retries.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_attempts
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

# ---------------- IAM for Lambda ----------------
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "careplan-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "dynamodb" {
  name = "careplan-dynamodb"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"]
      Resource = [aws_dynamodb_table.orders.arn]
    }]
  })
}

resource "aws_iam_role_policy" "sqs" {
  name = "careplan-sqs"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
      Resource = [aws_sqs_queue.jobs.arn]
    }]
  })
}

# ---------------- Lambda functions ----------------
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../package"
  output_path = "${path.module}/lambda.zip"
}

locals {
  common_env = {
    TABLE_NAME   = aws_dynamodb_table.orders.name
    QUEUE_URL    = aws_sqs_queue.jobs.url
    MAX_ATTEMPTS = tostring(var.max_attempts)
  }
  # for_each must not contain sensitive values, so iterate over names only.
  functions = toset(["create_order", "get_order", "generate_careplan"])
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/careplan-${replace(each.key, "_", "-")}"
  retention_in_days = 7
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "careplan-${replace(each.key, "_", "-")}"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "${each.key}.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = each.key == "generate_careplan" ? 120 : 15
  memory_size      = 512
  environment {
    variables = each.key == "generate_careplan" ? merge(local.common_env, {
      ANTHROPIC_API_KEY  = var.anthropic_api_key
      ANTHROPIC_BASE_URL = var.anthropic_base_url
      LLM_MODEL          = var.llm_model
    }) : local.common_env
  }
  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy_attachment.logs, aws_iam_role_policy.dynamodb, aws_iam_role_policy.sqs]
}

# SQS pushes to Lambda (vs. Celery workers pulling from Redis locally)
resource "aws_lambda_event_source_mapping" "jobs" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.fn["generate_careplan"].arn
  batch_size       = 1
  scaling_config {
    maximum_concurrency = 5
  }
}

# ---------------- API Gateway (HTTP API) ----------------
resource "aws_apigatewayv2_api" "http" {
  name          = "careplan-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

locals {
  routes = {
    create_order = "POST /orders"
    get_order    = "GET /orders/{id}"
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each               = local.routes
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn[each.key].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "fn" {
  for_each  = local.routes
  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
}

resource "aws_lambda_permission" "apigw" {
  for_each      = local.routes
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------- Outputs ----------------
output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "queue_url" {
  value = aws_sqs_queue.jobs.url
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "queue_arn" {
  value = aws_sqs_queue.jobs.arn
}


variable "expected_account_id" {
  type        = string
  description = "Account to deploy into, verified by the AWS provider."
}
