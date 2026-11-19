"""Replay one failed synthetic order; delete its DLQ message only after completion."""
import argparse
import json
import time
import boto3

parser = argparse.ArgumentParser()
parser.add_argument("--dlq-url", required=True)
parser.add_argument("--queue-url", required=True)
parser.add_argument("--table", required=True)
parser.add_argument("--order-id", required=True)
args = parser.parse_args()
session = boto3.Session()
sqs = session.client("sqs")
db = session.client("dynamodb")
messages = sqs.receive_message(QueueUrl=args.dlq_url, MaxNumberOfMessages=10,
                               WaitTimeSeconds=10, VisibilityTimeout=300).get("Messages", [])
selected = None
for message in messages:
    if json.loads(message["Body"]).get("order_id") == args.order_id:
        selected = message
    else:
        sqs.change_message_visibility(QueueUrl=args.dlq_url, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0)
if selected is None:
    raise SystemExit("Target message was not in this receive batch. Retry after checking the queue.")
started = time.perf_counter()
sqs.send_message(QueueUrl=args.queue_url, MessageBody=selected["Body"])
while time.perf_counter() - started < 240:
    item = db.get_item(TableName=args.table, Key={"pk": {"S": "ORDER#" + args.order_id}},
                       ConsistentRead=True).get("Item", {})
    if item.get("status", {}).get("S") == "completed":
        sqs.delete_message(QueueUrl=args.dlq_url, ReceiptHandle=selected["ReceiptHandle"])
        print(json.dumps({"order_id": args.order_id, "replay_to_completed_s": round(time.perf_counter()-started, 2)}))
        break
    time.sleep(1)
else:
    raise SystemExit("Replay did not finish in 240 seconds. Original DLQ message retained.")
