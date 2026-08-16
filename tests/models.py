"""Concrete models used only by django-tenant-apikeys' own test suite.

These are not part of the distributed package -- ``AbstractTenantAPIKey`` is
abstract by design, and a host project is expected to define its own
concrete subclass (see README.md). These stand in for that host project.
"""

from __future__ import annotations

from django.db import models

from django_tenant_apikeys.models import AbstractTenantAPIKey


class Tenant(models.Model):
    """A minimal stand-in for a host project's own tenant/organization model."""

    name = models.CharField(max_length=100)

    class Meta:
        app_label = "tests"

    def __str__(self) -> str:
        return self.name


class TenantAPIKey(AbstractTenantAPIKey):
    """Concrete API key model linked to :class:`Tenant`.

    This is the model ``TENANT_API_KEY_MODEL`` points at in
    :mod:`tests.settings`, exercising the "tenant relation exists" branch of
    ``TenantAPIKeyAuthentication``.
    """

    tenant = models.ForeignKey(Tenant, related_name="api_keys", on_delete=models.CASCADE)

    class Meta(AbstractTenantAPIKey.Meta):
        app_label = "tests"


class UnlinkedAPIKey(AbstractTenantAPIKey):
    """A concrete API key model with no ``tenant`` relation.

    Exercises the "no tenant relation" branch of ``TenantAPIKeyAuthentication``,
    where ``request.tenant`` must not be set.
    """

    class Meta(AbstractTenantAPIKey.Meta):
        app_label = "tests"
