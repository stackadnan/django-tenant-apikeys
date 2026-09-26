"""Django admin integration for django-tenant-apikeys."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import SafeString

from .models import AbstractTenantAPIKey, generate_api_key

if TYPE_CHECKING:
    # Same reasoning as the manager in models.py -- generic param for type
    # checkers only, real ModelAdmin isn't subscriptable without monkeypatch().
    _TenantAPIKeyAdminBase = admin.ModelAdmin["AbstractTenantAPIKey"]
else:
    _TenantAPIKeyAdminBase = admin.ModelAdmin


class TenantAPIKeyAdmin(_TenantAPIKeyAdminBase):
    """Register your concrete model against this (or a subclass of it)::

        @admin.register(OrganizationAPIKey)
        class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
            pass

    The raw key is generated on save and shown once via an admin message,
    never written to a form field or displayed again afterward.
    """

    list_display = (
        "name",
        "masked_key",
        "environment",
        "status",
        "created_at",
        "expires_at",
        "last_used_at",
    )
    list_filter = ("is_active", "environment", "created_at", "expires_at")
    search_fields = ("name", "prefix")
    # ``hashed_key`` is deliberately absent: it's ``editable=False`` (so it
    # never appears as an input), and there's no reason to render it either.
    readonly_fields = (
        "prefix",
        "created_at",
        "last_used_at",
        "revoked_at",
        "revoked_reason",
    )
    actions = ["revoke_selected"]

    @admin.display(description="Key")
    def masked_key(self, obj: AbstractTenantAPIKey) -> str:
        return f"{obj.prefix}.{'•' * 12}"

    @admin.display(description="Status")
    def status(self, obj: AbstractTenantAPIKey) -> str:
        if obj.is_expired:
            return "Expired"
        if not obj.is_active:
            return "Revoked" if obj.revoked_at else "Inactive"
        return "Active"

    @admin.action(description="Revoke selected API keys")
    def revoke_selected(
        self, request: HttpRequest, queryset: QuerySet[AbstractTenantAPIKey]
    ) -> None:
        count = 0
        for api_key in queryset.filter(is_active=True):
            api_key.revoke(reason="revoked via admin")
            count += 1
        self.message_user(request, f"Revoked {count} API key(s).", level=messages.WARNING)

    def save_model(
        self,
        request: HttpRequest,
        obj: AbstractTenantAPIKey,
        form: Any,
        change: bool,
    ) -> None:
        if change:
            if "is_active" in getattr(form, "changed_data", ()):
                # The checkbox is a second way to revoke/reactivate; keep
                # ``revoked_at``/``revoked_reason`` in step with it so a key
                # can't end up active-but-"revoked" or revoked-but-undated.
                if obj.is_active:
                    obj.revoked_at = None
                    obj.revoked_reason = ""
                elif obj.revoked_at is None:
                    obj.revoked_at = timezone.now()
                    obj.revoked_reason = "deactivated via admin"
            super().save_model(request, obj, form, change)
            return

        # Mint the prefix/hash here rather than trusting form data, then
        # save obj itself so the add-view redirect points at the real row.
        # ``environment`` comes from the form so the ``_live_``/``_test_``
        # prefix segment matches the column; scopes/allowed_ips/rate_limit
        # were already checked by the model's ``clean()`` via the form.
        full_key, key_prefix, hashed_key = generate_api_key(environment=obj.environment)
        obj.prefix = key_prefix
        obj.hashed_key = hashed_key
        super().save_model(request, obj, form, change)

        self.message_user(
            request,
            self._one_time_key_message(full_key),
            level=messages.WARNING,
        )

    @staticmethod
    def _one_time_key_message(full_key: str) -> SafeString:
        return format_html(
            "API key created successfully. Copy it now — "
            "it will not be shown again:<br><code>{}</code>",
            full_key,
        )
