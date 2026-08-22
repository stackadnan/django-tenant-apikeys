"""Django application configuration for django-tenant-apikeys."""

from __future__ import annotations

from django.apps import AppConfig


class DjangoTenantApikeysConfig(AppConfig):
    """No concrete models here (AbstractTenantAPIKey is abstract), so this
    only needs to be in INSTALLED_APPS if you're using the admin bundled
    with this package."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_tenant_apikeys"
    verbose_name = "Tenant API Keys"
