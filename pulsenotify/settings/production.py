"""Production overrides. Set DJANGO_SETTINGS_MODULE=pulsenotify.settings.production"""
import os

from .base import *  # noqa: F401,F403

DEBUG = False

# No fallbacks in production: fail loudly if a secret is missing.
SECRET_KEY = os.environ["SECRET_KEY"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
