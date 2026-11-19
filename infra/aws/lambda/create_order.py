"""POST /orders?source=web_form|clinic_json|pharma_xml  (API Gateway -> Lambda)

Adapter -> validation -> one DynamoDB transaction (same-day duplicate guard + order, status=pending) -> SQS -> 202.
The duplicate guard is a conditional write, so two identical requests racing each other cannot both succeed.
"""
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3

from adapters import AdapterError, get_adapter
from common import TABLE, ddb, response, validate

sqs = boto3.client("sqs")


def handler(event, context):
    t0 = time.perf_counter()
    source = (event.get("queryStringParameters") or {}).get("source", "web_form")
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        order = get_adapter(source).parse(body)
    except AdapterError as exc:
        return response(400, {"source": [str(exc)]})

    errors = validate(order)
    if errors:
        return response(400, errors)

    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    dup_key = f"DUP#{order.patient_mrn}#{order.medication_name.strip().lower()}#{now.date().isoformat()}"
    try:
        ddb.transact_write_items(TransactItems=[
            {"Put": {"TableName": TABLE,
                     "Item": {"pk": {"S": dup_key}, "order_id": {"S": order_id},
                              "expires_at": {"N": str(int(now.timestamp()) + 2 * 86400)}},
                     "ConditionExpression": "attribute_not_exists(pk)"}},
            {"Put": {"TableName": TABLE,
                     "Item": {"pk": {"S": f"ORDER#{order_id}"}, "source": {"S": order.source},
                              "payload": {"S": json.dumps(order.to_serializer_data())},
                              "status": {"S": "pending"}, "attempts": {"N": "0"},
                              "created_at": {"S": now.isoformat()}, "updated_at": {"S": now.isoformat()}}}},
        ])
    except ddb.exceptions.TransactionCanceledException as exc:
        reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
        if reasons and reasons[0] == "ConditionalCheckFailed":
            existing = ddb.get_item(TableName=TABLE, Key={"pk": {"S": dup_key}}).get("Item", {})
            return response(409, {"error": "duplicate_blocked",
                                  "existing_order_id": existing.get("order_id", {}).get("S"),
                                  "message": "Same patient + same medication already ordered today."})
        raise

    try:
        sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"order_id": order_id}))
    except Exception:
        return response(503, {"order_id": order_id, "error": "queue_delivery_failed",
                              "message": "Order saved. Operator queue replay required."})
    return response(202, {"order_id": order_id, "status": "pending", "source": order.source,
                          "server_ms": round((time.perf_counter() - t0) * 1000, 1)})
