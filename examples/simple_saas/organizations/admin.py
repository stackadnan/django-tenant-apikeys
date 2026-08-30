from django.contrib import admin

from django_tenant_apikeys.admin import TenantAPIKeyAdmin

from .models import Organization, OrganizationAPIKey


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    pass
