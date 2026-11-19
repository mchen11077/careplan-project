import uuid
from django.db import models


class Provider(models.Model):
    npi = models.CharField(primary_key=True, max_length=10)
    name = models.CharField(max_length=200)


class Order(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payload = models.JSONField()
    mrn = models.CharField(max_length=6)
    medication = models.CharField(max_length=200)
    service_date = models.DateField()
    status = models.CharField(max_length=20, default="queued")
    attempts = models.PositiveIntegerField(default=0)
    plan = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField()
    lease_until = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["mrn", "medication", "service_date"], name="one_medication_per_patient_day")]
