import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        with patch("boto3.client", return_value=self.client):
            self.worker = importlib.import_module("generate_careplan")
        self.worker.sqs = self.client
        self.event = {"Records": [{"body": json.dumps({"order_id": "test"}),
                                 "attributes": {"ApproximateReceiveCount": "1"}, "receiptHandle": "receipt"}]}

    def test_completed_redelivery_skips_model(self):
        with patch.object(self.worker, "get_order", return_value={"status": "completed"}), patch.object(self.worker, "call_claude") as model:
            self.worker.handler(self.event, None)
            model.assert_not_called()

    def test_retry_visibility_and_final_failure(self):
        for attempt, delay, status in [(1, 10, "retrying"), (2, 20, "retrying"), (3, 0, "failed")]:
            self.event["Records"][0]["attributes"]["ApproximateReceiveCount"] = str(attempt)
            with patch.dict("os.environ", {"QUEUE_URL": "queue"}), patch.object(self.worker, "get_order", return_value={"payload": "{}"}), patch.object(self.worker, "build_prompt", return_value="prompt"), patch.object(self.worker, "call_claude", side_effect=RuntimeError("injected")), patch.object(self.worker, "update_order") as update:
                with self.assertRaises(RuntimeError):
                    self.worker.handler(self.event, None)
                self.assertEqual(update.call_args.kwargs["status"], status)
                self.assertEqual(self.client.change_message_visibility.call_args.kwargs["VisibilityTimeout"], delay)


if __name__ == "__main__":
    unittest.main()
