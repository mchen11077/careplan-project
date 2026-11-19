# AWS deployment

The serverless implementation accepts structured orders through API Gateway, stores them in DynamoDB, and processes generation through SQS and Lambda.

```mermaid
flowchart LR
    Client --> Gateway[API Gateway]
    Gateway --> Submit[Submission Lambda]
    Submit --> Orders[(DynamoDB)]
    Submit --> Jobs[SQS]
    Jobs --> Worker[Generation Lambda]
    Worker --> Claude[Claude API]
    Worker --> Orders
    Jobs --> DLQ[Dead-letter queue]
    DLQ --> Alarm[CloudWatch alarm]
```

The React workspace currently uses the Django API. The AWS API is a separate deployment; `scripts/benchmark.py --aws` can exercise its submission and status endpoints.

## Prerequisites

- Terraform 1.5+ and an authenticated AWS CLI profile.
- An Anthropic API key and an available Claude model ID.
- Python dependencies from `infra/aws/requirements.txt`.

Run the following from the repository root:

```powershell
.venv/Scripts/python.exe -m pip install -r infra/aws/requirements.txt
.venv/Scripts/python.exe scripts/package_aws.py
terraform -chdir=infra/aws/terraform init
terraform -chdir=infra/aws/terraform validate
```

Copy `infra/aws/terraform/terraform.tfvars.example` to `terraform.tfvars` in the same directory. Set the expected AWS account ID and model ID, then provide the API key through `TF_VAR_anthropic_api_key` in the environment. Terraform state contains sensitive Lambda configuration; store it privately.

Review the plan before deploying resources:

```powershell
terraform -chdir=infra/aws/terraform plan
terraform -chdir=infra/aws/terraform apply
```

The account guard restricts deployment to the configured account. Deployment creates billable resources.

## Intake

`POST /orders?source=web_form` accepts flat JSON; `clinic_json` accepts nested JSON; `pharma_xml` accepts XML. Fixtures live in `backend/samples/`. The package script includes the shared adapters from `backend/shared/`, keeping the local and serverless intake contracts consistent.

`GET /orders/{id}` returns order status and the generated draft.

## Reliability and access

- A DynamoDB transaction records the order and same-day duplicate guard.
- SQS delivers jobs to the generation worker; failed attempts use 10- and 20-second delays before final failure and dead-letter handling.
- Completed orders skip repeated generation on redelivery.
- CloudWatch alarms report visible messages in the dead-letter queue.
- Application roles restrict data access to the orders table and jobs queue. DLQ replay uses a separate operator identity.

The Terraform configuration includes an IAM probe that checks application-table access and denial on an out-of-scope table:

```powershell
aws lambda invoke --function-name careplan-drill-iam-probe probe-result.json
Get-Content probe-result.json
```

## Recovery

After resolving the generation failure, replay a specific order from the dead-letter queue:

```powershell
.venv/Scripts/python.exe scripts/replay_dlq.py --order-id YOUR_ORDER_ID --dlq-url YOUR_DLQ_URL --queue-url YOUR_QUEUE_URL --table careplan-orders
```

The replay script deletes the original message only after observing completion. It requires SQS permissions on both queues and DynamoDB `GetItem` on the orders table. Unrelated messages are returned to the queue.

If order persistence succeeds but initial queue delivery fails, the API returns `503` with the order ID. Resend `{"order_id":"..."}` to the jobs queue after resolving the queue issue.

## Cleanup

```powershell
terraform -chdir=infra/aws/terraform destroy
```
