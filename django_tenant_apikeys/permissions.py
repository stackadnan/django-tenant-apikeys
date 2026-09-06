"""Django REST Framework permission classes: API key scopes, IP allowlists,
and per-key rate limiting."""

from __future__ import annotations

from collections.abc import Iterable

try:
    from rest_framework import exceptions
    from rest_framework.permissions import BasePermission
    from rest_framework.request import Request
    from rest_framework.views import APIView
except ImportError as exc:  # pragma: no cover - exercised only when DRF is absent
    raise ImportError(
        "django-tenant-apikeys requires djangorestframework to use "
        "HasAPIKeyScope. Install it with `pip install django-tenant-apikeys[drf]`."
    ) from exc

from .ip import get_client_ip
from .models import AbstractTenantAPIKey
from .ratelimit import check_rate_limit


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


class HasAllowedIP(BasePermission):
    """Denies access unless the request's client IP is covered by the
    authenticated key's ``allowed_ips`` -- an empty ``allowed_ips`` means
    any IP is fine, so this is a no-op for keys that don't restrict IPs::

        class OrdersView(APIView):
            authentication_classes = [TenantAPIKeyAuthentication]
            permission_classes = [HasAllowedIP, HasAPIKeyScope]

    Pair with ``TenantAPIKeyAuthentication`` -- this just returns False if
    ``request.auth`` isn't an API key instance. See
    ``django_tenant_apikeys.ip.get_client_ip`` for how the client IP is
    determined, including the (opt-in) trusted-proxy-header setting.
    """

    message = "This IP address is not permitted to use this API key."

    def has_permission(self, request: Request, view: APIView) -> bool:
        api_key = request.auth
        if not isinstance(api_key, AbstractTenantAPIKey):
            return False
        return api_key.is_ip_allowed(get_client_ip(request))


class WithinRateLimit(BasePermission):
    """Enforces the authenticated key's ``rate_limit``, if any::

        class OrdersView(APIView):
            authentication_classes = [TenantAPIKeyAuthentication]
            permission_classes = [WithinRateLimit, HasAPIKeyScope]

    A key with no ``rate_limit`` configured always passes. Once the limit is
    exceeded this raises ``Throttled`` (429 with a ``Retry-After`` header)
    instead of returning False -- ``PermissionDenied``'s 403 isn't the right
    status for "come back later".

    Also sets ``X-RateLimit-Limit``/``X-RateLimit-Remaining``/``X-RateLimit-Reset``
    on the response, success or not. Permission classes can't return a
    response of their own, but ``view.headers`` -- the same mechanism DRF
    itself uses for things like the ``Allow`` header -- gets copied onto
    whatever response the view (or the 429) ends up returning.
    """

    message = "Rate limit exceeded for this API key."

    def has_permission(self, request: Request, view: APIView) -> bool:
        api_key = request.auth
        if not isinstance(api_key, AbstractTenantAPIKey):
            return False

        result = check_rate_limit(api_key)
        if result.limit is not None:
            view.headers["X-RateLimit-Limit"] = str(result.limit)
            view.headers["X-RateLimit-Remaining"] = str(result.remaining)
            view.headers["X-RateLimit-Reset"] = str(result.reset_at)
        if not result.allowed:
            raise exceptions.Throttled(wait=result.retry_after)
        return True
