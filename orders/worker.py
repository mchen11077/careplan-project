from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from .generator import generate
from .models import Order


def process_one():
    now = timezone.now()
    eligible = (
        Q(status="queued", available_at__lte=now)
        | Q(status="generating", lease_until__lt=now)
    )
    candidate = Order.objects.filter(eligible).order_by("created_at").first()
    if candidate is None:
        return False
    if candidate.attempts >= 3:
        Order.objects.filter(pk=candidate.pk).filter(eligible).update(status="failed", lease_until=None)
        return True
    # Compare-and-swap claim prevents two workers from taking the same attempt.
    claimed = Order.objects.filter(pk=candidate.pk, attempts=candidate.attempts).filter(eligible).update(
        status="generating", attempts=candidate.attempts + 1,
        lease_until=now + timedelta(minutes=3),
    )
    if not claimed:
        return True
    attempt = candidate.attempts + 1
    current = Order.objects.filter(pk=candidate.pk, status="generating", attempts=attempt)
    try:
        plan = generate(candidate.payload)
    except Exception as error:
        message = str(error) if isinstance(error, RuntimeError) else "Generation failed. Try again later."
        current.update(
            status="failed" if attempt >= 3 else "queued",
            error=message, lease_until=None,
            available_at=timezone.now() + timedelta(seconds=10 * 2 ** (attempt - 1)),
        )
    else:
        current.update(status="completed", plan=plan, error="", lease_until=None)
    return True
