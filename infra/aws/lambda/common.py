"""Shared helpers for the three Lambda functions: DynamoDB access, validation, responses.

Single-table design (table name in env TABLE_NAME, partition key "pk"):
  ORDER#<uuid>                         the order: source, payload, status, attempts, care_plan, generation_ms, error
  DUP#<mrn>#<medication>#<yyyy-mm-dd>  same-day duplicate guard, written in the same transaction as the order
"""
import json
import os
import re
from decimal import Decimal

import boto3

TABLE = os.environ.get("TABLE_NAME", "careplan-orders")
ddb = boto3.client("dynamodb")

MRN_RE = re.compile(r"^\d{6}$")
NPI_RE = re.compile(r"^\d{10}$")
ICD10_RE = re.compile(r"^[A-TV-Z]\d{2}(\.\w{1,4})?$", re.IGNORECASE)


def validate(order):
    errors = {}
    if not MRN_RE.match(order.patient_mrn):
        errors["patient_mrn"] = "MRN must be exactly 6 digits"
    if not NPI_RE.match(order.provider_npi):
        errors["provider_npi"] = "NPI must be exactly 10 digits"
    if not ICD10_RE.match(order.primary_diagnosis_code):
        errors["primary_diagnosis_code"] = "Invalid ICD-10 code"
    for code in order.additional_diagnoses:
        if not ICD10_RE.match(code):
            errors.setdefault("additional_diagnoses", []).append(f"Invalid ICD-10 code: {code}")
    return errors


def get_order(order_id):
    item = ddb.get_item(TableName=TABLE, Key={"pk": {"S": f"ORDER#{order_id}"}}, ConsistentRead=True).get("Item")
    if not item:
        return None
    out = {}
    for k, v in item.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            out[k] = int(Decimal(v["N"]))
        elif "NULL" in v:
            out[k] = None
    return out


def update_order(order_id, **fields):
    names, values, sets = {}, {}, []
    for i, (k, v) in enumerate(fields.items()):
        names[f"#f{i}"] = k
        if v is None:
            values[f":v{i}"] = {"NULL": True}
        elif isinstance(v, (int, float)):
            values[f":v{i}"] = {"N": str(v)}
        else:
            values[f":v{i}"] = {"S": str(v)}
        sets.append(f"#f{i} = :v{i}")
    ddb.update_item(TableName=TABLE, Key={"pk": {"S": f"ORDER#{order_id}"}},
                    UpdateExpression="SET " + ", ".join(sets),
                    ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def response(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body, default=str)}
