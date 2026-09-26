"""Django Ninja authentication integration for django-tenant-apikeys."""

from __future__ import annotations

try:
    from ninja.security import APIKeyHeader
except ImportError as exc:  # pragma: no cover - exercised only when Ninja is absent
    raise ImportError(
        "django-tenant-apikeys requires django-ninja to use TenantAPIKeyAuth. "
        "Install it with `pip install django-tenant-apikeys[ninja]`."
    ) from exc

from django.http import HttpRequest

from .models import AbstractTenantAPIKey, get_api_key_model

#: Same scheme TenantAPIKeyAuthentication (DRF) responds to.
API_KEY_KEYWORD = "Api-Key"


class TenantAPIKeyAuth(APIKeyHeader):
    """Authenticates ``Authorization: Api-Key <key>`` requests for Django Ninja.

    Mirrors ``TenantAPIKeyAuthentication``'s rejection rules -- unknown,
    tampered, inactive, or expired keys are all treated as authentication
    failure, never as anonymous access -- and the same success behaviour:
    ``record_usage()`` is called, and ``request.tenant`` is attached if the
    resolved model has a ``tenant`` relation. Ninja itself turns a ``None``
    return from ``authenticate()`` into a 401 for any operation using this
    class, so there's no separate "no header" vs "bad key" outcome to
    signal the way DRF's authenticator can via ``AuthenticationFailed`` --
    both simply fail closed here.

    Resolves the model from ``TENANT_API_KEY_MODEL`` by default; set
    ``model`` on a subclass to skip the setting, same as the DRF class::

        class PartnerAPIKeyAuth(TenantAPIKeyAuth):
            model = PartnerAPIKey

    ::

        from ninja import NinjaAPI
        from django_tenant_apikeys.ninja import TenantAPIKeyAuth

        api = NinjaAPI(auth=TenantAPIKeyAuth())

        @api.get("/orders")
        def list_orders(request):
            if not request.auth.has_scope("orders:read"):
                return 403, {"detail": "missing required scope"}
            return request.tenant.orders.all()

    Ninja has no permission-class system to hook policy checks into the way
    DRF does (see ``HasAllowedIP``/``WithinRateLimit`` there), so an IP
    allowlist or rate limit is enforced the same way scopes are here --
    inline, using the same shared functions DRF's permission classes call::

        from django.http import JsonResponse

        from django_tenant_apikeys.ip import get_client_ip
        from django_tenant_apikeys.ratelimit import check_rate_limit

        @api.get("/orders")
        def list_orders(request):
            if not request.auth.is_ip_allowed(get_client_ip(request)):
                return JsonResponse({"detail": "IP not allowed"}, status=403)
            result = check_rate_limit(request.auth)
            if not result.allowed:
                return JsonResponse(
                    {"detail": "rate limit exceeded", "retry_after": result.retry_after},
                    status=429,
                )
            ...
    """

    param_name = "Authorization"
    openapi_scheme = "apikey"
    model: type[AbstractTenantAPIKey] | None = None

    def get_model(self) -> type[AbstractTenantAPIKey]:
        return self.model or get_api_key_model()

    def authenticate(self, request: HttpRequest, key: str | None) -> AbstractTenantAPIKey | None:
        if not key:
            return None

        parts = key.split()
        if len(parts) != 2 or parts[0].lower() != API_KEY_KEYWORD.lower():
            return None
        raw_key = parts[1]

        model = self.get_model()
        key_prefix, _sep, _secret = raw_key.partition(".")
        try:
            api_key: AbstractTenantAPIKey = model.objects.get(prefix=key_prefix)
        except model.DoesNotExist:
            return None

        if not api_key.verify_key(raw_key):
            return None
        if not api_key.is_active or api_key.is_expired:
            return None

        api_key.record_usage()

        if hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant  # type: ignore[attr-defined]

        return api_key
