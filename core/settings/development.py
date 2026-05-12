from .base import *

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Print emails to console in dev
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable throttling in dev
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []

INSTALLED_APPS += ["debug_toolbar"]  