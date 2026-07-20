from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reports"
    verbose_name = "Reports & Analytics"

    def ready(self):
        # Import signal handlers so they register.
        from reports import signals  # noqa: F401
