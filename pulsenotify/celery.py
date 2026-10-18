import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pulsenotify.settings.local")

app = Celery("pulsenotify")
# Read every CELERY_* setting from Django settings (including CELERY_BEAT_SCHEDULE).
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
