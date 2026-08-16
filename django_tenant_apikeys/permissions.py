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
    """Grant access only if the authenticated API key has every required scope.

    Views declare their requirement via a ``required_scopes`` attribute::

        class OrdersView(APIView):
            authentication_classes = [TenantAPIKeyAuthentication]
            permission_classes = [HasAPIKeyScope]
            required_scopes = ["orders:read"]

    A view with no ``required_scopes`` attribute (or an empty one) is
    accessible to any successfully authenticated API key. Each listed scope
    is checked with :meth:`AbstractTenantAPIKey.has_scope`, which itself
    honors ``"*"`` and namespaced (``"orders:*"``) wildcards -- all
    required scopes must be satisfied for the check to pass.

    This permission always denies access when ``request.auth`` is not an
    API key instance (e.g. no authentication occurred, or a different
    authentication backend populated ``request.auth``), so it should be
    paired with :class:`~django_tenant_apikeys.authentication.TenantAPIKeyAuthentication`.
    """

    message = "This API key does not have the required scope(s) for this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        api_key = request.auth
        if not isinstance(api_key, AbstractTenantAPIKey):
            return False

        required_scopes: Iterable[str] = getattr(view, "required_scopes", [])
        return all(api_key.has_scope(scope) for scope in required_scopes)
