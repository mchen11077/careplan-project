# AWS version

API Gateway HTTP API -> submission Lambda -> DynamoDB transaction -> SQS -> generation Lambda -> DynamoDB. GET /orders/{id} returns progress and the draft. The React app uses the Django API for local demonstrations; scripts/benchmark.py can exercise the AWS API directly.

## Prepare and validate

Install Terraform 1.5+ and configure an AWS CLI profile for your account.

```powershell
.venv/Scripts/python.exe -m pip install -r aws/requirements.txt
.venv/Scripts/python.exe scripts/package_aws.py
terraform -chdir=aws/infra init
terraform -chdir=aws/infra validate
```

Copy terraform.tfvars.example to terraform.tfvars and set your account ID and available model ID. Set TF_VAR_anthropic_api_key in the environment. Terraform stores the sensitive Lambda environment value in state, so keep state private.

Review `terraform -chdir=aws/infra plan` before applying. This creates billable resources. The account guard prevents applying to an unintended account. Deploy with `terraform -chdir=aws/infra apply`.

## Intake adapters

POST /orders?source=web_form accepts flat JSON. clinic_json accepts nested JSON. pharma_xml accepts XML. samples/ contains examples. The package script copies shared/adapters.py into the Lambda bundle so the same registry is used locally and in AWS. Extend the registry by adding an adapter class; business logic consumes InternalOrder.

## IAM verification

The recovered policies restrict data access to the orders table and jobs queue. CloudWatch log access uses AWSLambdaBasicExecutionRole. The worker role has no access to the DLQ; replay is an operator action. drill.tf includes a probe Lambda with the application role.

```powershell
aws lambda invoke --function-name careplan-drill-iam-probe probe-result.json
Get-Content probe-result.json
```

Expected result: in_scope allowed, out_of_scope AccessDeniedException. This is a live permission check and requires a deployment.

For an independent static policy baseline, run the following from the repository root with uv installed. Compare its output against the existing policies before changing them.

```powershell
uvx iam-policy-autopilot@latest generate-policies (Resolve-Path aws/lambda/create_order.py) (Resolve-Path aws/lambda/common.py) (Resolve-Path aws/lambda/generate_careplan.py) --service-hints dynamodb sqs --tf-dir aws/infra --pretty
```

## Failure and replay drill

Use only synthetic fixtures. Set the worker API key to an invalid value with Terraform, submit an order using scripts/benchmark.py --aws --url YOUR_API_URL, and wait for three failed attempts and a DLQ message. The worker delays retries by 10 and 20 seconds. SQS timing and throttling affect the actual elapsed time. CloudWatch alarms when the DLQ has a visible message.

Fix the API key through Terraform first. Then:

```powershell
.venv/Scripts/python.exe scripts/replay_dlq.py --order-id YOUR_ORDER_ID --dlq-url YOUR_DLQ_URL --queue-url YOUR_QUEUE_URL --table careplan-orders
```

The script replays the specified order, measures recovery, and deletes the original DLQ message only after observing completion. It requires an operator identity with SQS permissions on both queues and DynamoDB GetItem on the orders table. It returns unrelated received messages to the queue. A receive may not include the target message; rerun after checking queue contents.

The worker preserves the last error when replay completes. Completed orders skip repeated generation when SQS redelivers a message.

If the initial database write succeeds but queue delivery fails, the submission returns 503 with the order ID. An operator can resend {"order_id":"..."} to the jobs queue. The duplicate guard prevents a second order from being created.

## Timing evidence

Run scripts/benchmark.py with --aws to capture submission latency, worker generation duration, and observed end-to-end duration. Run without --aws for the Django version. Polling and queue wait are included in observed completion time. See evidence/README.md for what the historical logs actually establish.

After your demonstration, remove resources with terraform -chdir=aws/infra destroy.
