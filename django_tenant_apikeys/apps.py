"""Django application configuration for django-tenant-apikeys."""

from __future__ import annotations

from django.apps import AppConfig


class DjangoTenantApikeysConfig(AppConfig):
    """Default :class:`~django.apps.AppConfig` for this package.

    Registering ``"django_tenant_apikeys"`` in ``INSTALLED_APPS`` is only
    required if your project uses the bundled :mod:`django.contrib.admin`
    integration or otherwise needs Django to discover this app explicitly.
    Since :class:`~django_tenant_apikeys.models.AbstractTenantAPIKey` is
    abstract, this app defines no concrete models and creates no database
    tables of its own.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "django_tenant_apikeys"
    verbose_name = "Tenant API Keys"
