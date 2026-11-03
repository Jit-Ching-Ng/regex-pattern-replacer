"""Delete datasets (and their files) older than a given age.

Run it on a schedule (cron / platform job) so anonymous uploads do not pile up:

    python manage.py purge_datasets --hours 24
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from processor.models import Dataset
from processor.services.datasets import DatasetService


class Command(BaseCommand):
    help = "Delete datasets that have not been updated for the given number of hours."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=float, default=24)

    def handle(self, *args, hours: float, **options):
        cutoff = timezone.now() - timedelta(hours=hours)
        service = DatasetService()
        stale = Dataset.objects.filter(updated_at__lt=cutoff)
        count = 0
        for dataset in stale.iterator():
            service.delete(dataset)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} dataset(s) older than {hours:g}h."))
