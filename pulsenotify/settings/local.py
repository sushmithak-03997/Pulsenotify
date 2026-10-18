"""Local development overrides."""
import os

from .base import *  # noqa: F401,F403

DEBUG = True

if os.environ.get("USE_SQLITE") == "1":
    # Optional shortcut (no Docker needed) e.g. for a quick `USE_SQLITE=1 python manage.py test`
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "pulsenotify"),
            "USER": os.environ.get("POSTGRES_USER", "pulse_user"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "pulse_pass"),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
