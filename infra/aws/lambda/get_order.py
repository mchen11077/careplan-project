"""GET /orders/{id}  (API Gateway -> Lambda). The frontend polls this until status is completed/failed."""
import uuid

from common import get_order, response


def handler(event, context):
    order_id = (event.get("pathParameters") or {}).get("id", "")
    try:
        uuid.UUID(order_id)
    except ValueError:
        return response(400, {"error": "invalid order id"})
    o = get_order(order_id)
    if not o:
        return response(404, {"error": "not found"})
    return response(200, {"order_id": order_id, "source": o.get("source"), "status": o.get("status"),
                          "attempts": o.get("attempts"), "generation_ms": o.get("generation_ms"),
                          "error": o.get("error"), "created_at": o.get("created_at"),
                          "updated_at": o.get("updated_at"), "care_plan": o.get("care_plan")})
