"""Django REST Framework permission class enforcing API key scopes."""

from __future__ import annotations

from collections.abc import Iterable

try:
    from rest_framework.permissions import BasePermission
    from rest_framework.request import Request
    from rest_framework.views import APIView
except ImportError as exc:  # pragma: no cover - exercised only when DRF is absent
    raise ImportError(
        "django-tenant-apikeys requires djangorestframework to use "
        "HasAPIKeyScope. Install it with `pip install django-tenant-apikeys[drf]`."
    ) from exc

from .models import AbstractTenantAPIKey


class HasAPIKeyScope(BasePermission):
    """Denies access unless the authenticated key has every scope in the
    view's ``required_scopes``::

        class OrdersView(APIView):
            authentication_classes = [TenantAPIKeyAuthentication]
            permission_classes = [HasAPIKeyScope]
            required_scopes = ["orders:read"]

    No ``required_scopes`` (or an empty list) means any authenticated key
    is allowed through. Pair with ``TenantAPIKeyAuthentication`` -- this
    just returns False if ``request.auth`` isn't an API key instance.
    """

    message = "This API key does not have the required scope(s) for this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        api_key = request.auth
        if not isinstance(api_key, AbstractTenantAPIKey):
            return False

        required_scopes: Iterable[str] = getattr(view, "required_scopes", [])
        return all(api_key.has_scope(scope) for scope in required_scopes)
