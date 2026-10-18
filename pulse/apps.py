from django.apps import AppConfig


class PulseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pulse"

    def ready(self):
        # Importing registers the post_save receiver that creates UserProfile.
        from . import signals  # noqa: F401
