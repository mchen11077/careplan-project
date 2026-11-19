import time
from django.core.management.base import BaseCommand
from orders.worker import process_one


class Command(BaseCommand):
    help = "Process durable generation jobs. Restart safely after interruption."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        if options["once"]:
            process_one()
            return
        self.stdout.write("Worker ready. Press Ctrl+C to stop.")
        try:
            while True:
                if not process_one():
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
