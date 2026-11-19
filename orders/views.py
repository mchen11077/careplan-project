import csv
import json
from datetime import date
from pathlib import Path
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import Order, Provider
from .validation import IntakeError, duplicate_warnings, normalize


def serialize(order):
    return {
        "id": str(order.pk), "patient": order.payload["patient_first_name"] + " " + order.payload["patient_last_name"],
        "mrn": order.mrn, "medication": order.payload["medication_name"],
        "status": order.status, "attempts": order.attempts, "error": order.error,
        "plan": order.plan, "created_at": order.created_at.isoformat(),
    }


@require_GET
def health(request):
    import os
    return JsonResponse({"csrf": get_token(request), "mode": os.environ.get("CAREPLAN_MODE", "demo")})


def orders(request):
    if request.method == "GET":
        return JsonResponse({"orders": [serialize(order) for order in Order.objects.order_by("-created_at")[:100]]})
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        raw = json.loads(request.body)
        data = normalize(raw)
    except (ValueError, UnicodeDecodeError) as error:
        return JsonResponse({"error": str(error)}, status=400)
    try:
        with transaction.atomic():
            provider, _ = Provider.objects.get_or_create(npi=data["provider_npi"], defaults={"name": data["provider_name"]})
            if provider.name.casefold() != data["provider_name"].casefold():
                return JsonResponse({"error": "This NPI already belongs to a different provider name."}, status=409)
            if Order.objects.filter(mrn=data["patient_mrn"], medication=data["medication_name"].casefold(), service_date=date.today()).exists():
                return JsonResponse({"error": "An order for this patient and medication already exists today."}, status=409)
            existing = list(Order.objects.all())
            for other in existing:
                p = other.payload
                if p["provider_npi"] == data["provider_npi"] and p["provider_name"].casefold() != data["provider_name"].casefold():
                    return JsonResponse({"error": "This NPI already belongs to a different provider name."}, status=409)
            warnings = duplicate_warnings(data, existing)
            if warnings and not raw.get("confirm_warnings", False):
                return JsonResponse({"warnings": warnings}, status=409)
            order = Order.objects.create(
                payload=data, mrn=data["patient_mrn"], medication=data["medication_name"].casefold(),
                service_date=date.today(), available_at=timezone.now(),
            )
    except IntegrityError:
        return JsonResponse({"error": "An order for this patient and medication already exists today."}, status=409)
    return JsonResponse(serialize(order), status=202)


@require_GET
def detail(request, order_id):
    return JsonResponse(serialize(get_object_or_404(Order, pk=order_id)))


@require_POST
def retry(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    changed = Order.objects.filter(pk=order.pk, status="failed").update(
        status="queued", attempts=0, error="", available_at=timezone.now(), lease_until=None,
    )
    if not changed:
        return JsonResponse({"error": "Only failed orders can be retried."}, status=409)
    order.refresh_from_db()
    return JsonResponse(serialize(order), status=202)


@require_GET
def download(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    if order.status != "completed":
        return JsonResponse({"error": "The draft is not ready yet."}, status=409)
    response = HttpResponse(order.plan, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="draft-{order.pk}.txt"'
    return response


@require_GET
def export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order ID", "MRN", "Medication", "Status", "Created at"])
    for order in Order.objects.order_by("created_at").iterator():
        values = [str(order.pk), order.mrn, order.payload["medication_name"], order.status, order.created_at.isoformat()]
        writer.writerow(["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    return response


@require_GET
def frontend(request, path=""):
    root = settings.BASE_DIR / "frontend" / "dist"
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        return HttpResponse(status=404)
    if not target.is_file():
        target = root / "index.html"
    if not target.exists():
        return HttpResponse("Build the frontend first. See README.", status=503)
    import mimetypes
    return FileResponse(target.open("rb"), content_type=mimetypes.guess_type(str(target))[0] or "application/octet-stream")
