"""Django admin integration for django-tenant-apikeys."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.safestring import SafeString

from .models import AbstractTenantAPIKey, generate_api_key

if TYPE_CHECKING:
    # See the equivalent TYPE_CHECKING branch in models.py: django-stubs
    # models ModelAdmin as generic, but subscripting the real runtime class
    # requires django_stubs_ext.monkeypatch(), which this package can't
    # assume every consumer has called. `else` is what actually executes.
    _TenantAPIKeyAdminBase = admin.ModelAdmin["AbstractTenantAPIKey"]
else:
    _TenantAPIKeyAdminBase = admin.ModelAdmin


class TenantAPIKeyAdmin(_TenantAPIKeyAdminBase):
    """Base ``ModelAdmin`` for concrete subclasses of :class:`AbstractTenantAPIKey`.

    Register your concrete model against this class (or a subclass of it)::

        @admin.register(OrganizationAPIKey)
        class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
            pass

    The raw secret key is generated on save and shown to the operator
    exactly once via a Django admin message; it is never persisted or
    rendered again afterwards. List and detail views only ever display the
    non-secret ``prefix``, so the raw key cannot leak through the admin
    after creation -- not even to staff with change permissions.
    """

    list_display = ("name", "masked_key", "is_active", "created_at", "expires_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "hashed_key", "created_at")

    @admin.display(description="Key")
    def masked_key(self, obj: AbstractTenantAPIKey) -> str:
        """Render the key's public prefix with the secret portion masked out."""
        return f"{obj.prefix}.{'•' * 12}"

    def save_model(
        self,
        request: HttpRequest,
        obj: AbstractTenantAPIKey,
        form: Any,
        change: bool,
    ) -> None:
        if change:
            super().save_model(request, obj, form, change)
            return

        # New key: mint a fresh prefix/hash pair for this row rather than
        # trusting anything the (readonly) form fields might contain, then
        # persist obj itself so the admin's add-view redirect and success
        # message continue to reference the row that was actually saved.
        full_key, key_prefix, hashed_key = generate_api_key()
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
