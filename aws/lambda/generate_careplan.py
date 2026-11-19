"""SQS -> Lambda worker. Calls Claude, stores the care plan.

Retry policy: on failure we push the message's next visibility out exponentially (10s, 20s, ...) and re-raise,
so SQS redelivers it. After MAX_ATTEMPTS receives the queue's redrive policy moves it to the Dead Letter Queue,
instead of retrying (and paying) forever.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3

from common import get_order, update_order

sqs = boto3.client("sqs")
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
BASE_DELAY_S = 10


def _now():
    return datetime.now(timezone.utc).isoformat()

SYSTEM_PROMPT = (
    "You are a clinical pharmacist at a specialty pharmacy. Write a concise pharmacist care plan with these "
    "sections: Problem List / Drug Therapy Problems, Goals (SMART), Pharmacist Interventions, Monitoring Plan. "
    "Use only the patient information provided. Keep it under 600 words."
)


def build_prompt(p):
    lines = [
        "## PATIENT DEMOGRAPHICS",
        f"- Name: {p['patient_first_name']} {p['patient_last_name']}",
        f"- MRN: {p['patient_mrn']}",
        f"- DOB: {p.get('patient_date_of_birth') or 'Not provided'}",
        f"- Sex: {p.get('patient_sex') or 'Not provided'}",
        f"- Weight: {p.get('patient_weight_kg') or 'Not provided'} kg",
        f"- Allergies: {p.get('patient_allergies') or 'Not documented'}",
        "", "## MEDICATION", f"- Current Medication Order: {p['medication_name']}",
        "", "## DIAGNOSES",
        f"- Primary: {p['primary_diagnosis_code']} {p.get('primary_diagnosis_description', '')}",
    ]
    lines += [f"- Secondary: {dx}" for dx in p.get("additional_diagnoses", [])]
    meds = p.get("medication_history") or []
    lines += ["", "## HOME MEDS"] + ([f"- {m}" for m in meds] if meds else ["- None documented"])
    lines += ["", "## CLINICAL NOTES", p["patient_records"]]
    return "Please generate a pharmacist care plan for the following patient:\n\n" + "\n".join(lines)


def call_claude(prompt):
    # The isolated AWS drill never calls an external model.
    mode = os.environ["ANTHROPIC_API_KEY"]
    if mode == "careplan-drill-fail":
        raise RuntimeError("Injected model failure for the AWS recovery drill")
    if mode == "careplan-drill-recover":
        return "Synthetic response for the AWS recovery drill."
    req = urllib.request.Request(
        os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages",
        data=json.dumps({
            "model": os.environ["LLM_MODEL"], "max_tokens": 3000, "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8"),
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json", "user-agent": "careplan-coursework/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=100) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Anthropic API HTTP {exc.code}") from None
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    if not text:
        # A 200 response with no text is a failure, not a completed care plan.
        kinds = [b.get("type") for b in data.get("content", [])]
        raise RuntimeError("Generation returned no text")
    return text


def handler(event, context):
    for record in event["Records"]:  # batch_size = 1
        order_id = json.loads(record["body"])["order_id"]
        attempt = int(record["attributes"]["ApproximateReceiveCount"])
        previous = get_order(order_id)
        if previous and previous.get("status") == "completed":
            continue
        update_order(order_id, status="processing", attempts=attempt, updated_at=_now())
        try:
            payload = json.loads(get_order(order_id)["payload"])
            t0 = time.perf_counter()
            care_plan = call_claude(build_prompt(payload))
            ms = int((time.perf_counter() - t0) * 1000)
            update_order(order_id, status="completed", care_plan=care_plan, generation_ms=ms,
                         updated_at=_now())
            print(json.dumps({"event": "care_plan_completed", "order_id": order_id, "attempt": attempt, "ms": ms}))
        except Exception as exc:
            final = attempt >= MAX_ATTEMPTS
            update_order(order_id, status="failed" if final else "retrying", error=str(exc)[:500], updated_at=_now())
            delay = 0 if final else BASE_DELAY_S * 2 ** (attempt - 1)
            sqs.change_message_visibility(QueueUrl=os.environ["QUEUE_URL"],
                                          ReceiptHandle=record["receiptHandle"], VisibilityTimeout=delay)
            print(json.dumps({"event": "care_plan_failed", "order_id": order_id, "attempt": attempt,
                              "final": final, "next_retry_s": None if final else delay, "error": str(exc)[:200]}))
            raise
