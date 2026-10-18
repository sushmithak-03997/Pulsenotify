#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

from dotenv import load_dotenv


def main():
    load_dotenv()  # DJANGO_SETTINGS_MODULE and all secrets come from .env
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pulsenotify.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed and is your virtualenv active?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
