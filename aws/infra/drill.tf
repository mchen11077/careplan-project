resource "aws_sns_topic" "drill_alerts" {
  name = "careplan-drill-alerts"
}

resource "aws_sns_topic_policy" "drill_alerts" {
  arn = aws_sns_topic.drill_alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TopicOwner"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.expected_account_id}:root" }
        Action    = ["sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:DeleteTopic", "sns:Subscribe", "sns:ListSubscriptionsByTopic", "sns:Publish", "sns:AddPermission", "sns:RemovePermission"]
        Resource  = aws_sns_topic.drill_alerts.arn
      },
      {
        Sid       = "CloudWatchDrillAlarm"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.drill_alerts.arn
        Condition = {
          StringEquals = { "aws:SourceAccount" = "${var.expected_account_id}" }
          ArnEquals    = { "aws:SourceArn" = "arn:aws:cloudwatch:${var.region}:${var.expected_account_id}:alarm:careplan-drill-dlq-depth" }
        }
      }
    ]
  })
}

resource "aws_sqs_queue" "drill_alerts" {
  name = "careplan-drill-alerts"
}

resource "aws_sqs_queue_policy" "drill_alerts" {
  queue_url = aws_sqs_queue.drill_alerts.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.drill_alerts.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.drill_alerts.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "drill_alerts" {
  topic_arn  = aws_sns_topic.drill_alerts.arn
  protocol   = "sqs"
  endpoint   = aws_sqs_queue.drill_alerts.arn
  depends_on = [aws_sqs_queue_policy.drill_alerts]
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "careplan-drill-dlq-depth"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.drill_alerts.arn]
  depends_on          = [aws_sns_topic_subscription.drill_alerts]
}

output "alert_queue_url" {
  value = aws_sqs_queue.drill_alerts.url
}

data "archive_file" "iam_probe" {
  type        = "zip"
  output_path = "${path.module}/iam-probe.zip"
  source {
    filename = "probe.py"
    content  = <<-PYTHON
      import os
      import boto3
      from botocore.exceptions import ClientError

      def handler(event, context):
          db = boto3.client("dynamodb")
          table = os.environ["ORDERS_TABLE"]
          key = {"pk": {"S": "iam-probe-no-record"}}
          db.get_item(TableName=table, Key=key)
          try:
              db.get_item(TableName=table + "-outside-scope", Key=key)
          except ClientError as error:
              return {"in_scope": "allowed", "out_of_scope": error.response["Error"]["Code"]}
          return {"in_scope": "allowed", "out_of_scope": "allowed"}
    PYTHON
  }
}

resource "aws_cloudwatch_log_group" "iam_probe" {
  name              = "/aws/lambda/careplan-drill-iam-probe"
  retention_in_days = 1
}

resource "aws_lambda_function" "iam_probe" {
  function_name    = "careplan-drill-iam-probe"
  role             = aws_iam_role.lambda.arn
  handler          = "probe.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.iam_probe.output_path
  source_code_hash = data.archive_file.iam_probe.output_base64sha256
  timeout          = 15
  environment {
    variables = { ORDERS_TABLE = aws_dynamodb_table.orders.name }
  }
  depends_on = [aws_iam_role_policy.dynamodb, aws_cloudwatch_log_group.iam_probe]
}
