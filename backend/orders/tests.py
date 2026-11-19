import json
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from .models import Order
from .worker import process_one

DATA = dict(patient_mrn="123456", patient_first_name="Alex", patient_last_name="Example",
            patient_date_of_birth="1990-01-01", primary_diagnosis_code="Z00.00",
            medication_name="Demo medication", provider_name="Demo Provider", provider_npi="0000000000")


class OrderTests(TestCase):
    def submit(self, **changes):
        return self.client.post("/api/orders", json.dumps(DATA | changes), content_type="application/json")

    def test_end_to_end(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        self.assertTrue(process_one())
        order_id = response.json()["id"]
        result = self.client.get("/api/orders/" + order_id).json()
        self.assertEqual(result["status"], "completed")
        self.assertIn("Monitoring Plan", result["plan"])
        self.assertEqual(self.client.get("/api/orders/" + order_id + "/download").status_code, 200)
        self.assertFalse(process_one())

    def test_duplicate_and_provider_conflict(self):
        self.assertEqual(self.submit().status_code, 202)
        self.assertEqual(self.submit(confirm_warnings=True).status_code, 409)
        self.assertEqual(self.submit(patient_mrn="654321", provider_name="Other").status_code, 409)
        self.assertEqual(Order.objects.count(), 1)

    def test_identity_warning_confirmation(self):
        self.submit()
        self.assertIn("warnings", self.submit(patient_mrn="654321").json())
        self.assertEqual(self.submit(patient_mrn="654321", confirm_warnings=True).status_code, 202)

    def test_validation(self):
        self.assertEqual(self.submit(patient_mrn="bad").status_code, 400)
        self.assertEqual(self.submit(patient_date_of_birth="2099-01-01").status_code, 400)
        self.assertEqual(self.submit(primary_diagnosis_code="wrong").status_code, 400)

    @patch("orders.worker.generate", side_effect=RuntimeError("Provider unavailable."))
    def test_failure_retry_and_recovery(self, generate):
        response = self.submit()
        for _ in range(3):
            Order.objects.update(available_at=timezone.now())
            process_one()
        order = Order.objects.get()
        self.assertEqual(order.status, "failed")
        self.assertEqual(order.attempts, 3)
        self.assertEqual(self.client.get(f"/api/orders/{order.pk}/download").status_code, 409)
        self.assertEqual(self.client.post(f"/api/orders/{order.pk}/retry").status_code, 202)
        generate.side_effect = None
        generate.return_value = "Recovered draft"
        process_one()
        order.refresh_from_db()
        self.assertEqual(order.plan, "Recovered draft")

    def test_csrf(self):
        from django.test import Client
        response = Client(enforce_csrf_checks=True).post("/api/orders", "{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_all_intake_formats(self):
        from pathlib import Path
        from django.conf import settings
        samples = Path(settings.BASE_DIR) / "samples"
        for source, name, content in [
            ("web_form", "web_form.json", "application/json"),
            ("clinic_json", "clinic.json", "application/json"),
            ("pharma_xml", "pharma.xml", "application/xml"),
        ]:
            Order.objects.all().delete()
            response = self.client.post("/api/orders?source=" + source, (samples / name).read_bytes(), content_type=content)
            self.assertEqual(response.status_code, 202, response.content)
