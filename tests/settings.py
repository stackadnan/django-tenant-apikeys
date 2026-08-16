"""Minimal Django settings for running django-tenant-apikeys' test suite.

Not shipped as part of the distributed package -- used only by pytest-django
(see ``[tool.pytest.ini_options]`` in ``pyproject.toml``) and by the CI
workflows.
"""

from __future__ import annotations

SECRET_KEY = "django-insecure-test-secret-key-not-for-production-use"

DEBUG = True

USE_TZ = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_tenant_apikeys",
    "tests",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The concrete key model that TenantAPIKeyAuthentication resolves by default.
# See tests/models.py for its definition.
TENANT_API_KEY_MODEL = "tests.TenantAPIKey"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "django_tenant_apikeys.authentication.TenantAPIKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [],
}
