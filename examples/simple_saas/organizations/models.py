from django.db import models

from django_tenant_apikeys.models import AbstractTenantAPIKey


class Organization(models.Model):
    """The tenant. In a real project this is whatever your SaaS calls an
    account -- Organization, Workspace, Account, Team, ..."""

    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name


class OrganizationAPIKey(AbstractTenantAPIKey):
    """The concrete key model. AbstractTenantAPIKey ships abstract on
    purpose -- this `tenant` field is the one line every project has to
    add itself to wire the two together."""

    tenant = models.ForeignKey(
        Organization,
        related_name="api_keys",
        on_delete=models.CASCADE,
    )
