"""Django Ninja integration for django-tenant-apikeys."""

from __future__ import annotations

import threading
from collections.abc import Sequence

try:
    from ninja.errors import HttpError
    from ninja.security import APIKeyHeader
except ImportError as exc:  # pragma: no cover - exercised only when Ninja is absent
    raise ImportError(
        "django-tenant-apikeys requires django-ninja to use TenantAPIKeyAuth. "
        "Install it with `pip install django-tenant-apikeys[ninja]`."
    ) from exc

from django.http import HttpRequest

from .core import (
    API_KEY_KEYWORD,
    MISSING_SCOPE_MESSAGE,
    APIKeyRejected,
    authenticate_key,
    client_message,
)
from .ip import get_client_ip
from .models import AbstractTenantAPIKey, get_api_key_model
from .ratelimit import RateLimitResult, check_rate_limit

__all__ = ["API_KEY_KEYWORD", "TenantAPIKeyAuth"]


class TenantAPIKeyAuth(APIKeyHeader):
    """Authenticates ``Authorization: Api-Key <key>`` requests for Django Ninja.

    A thin adapter over :func:`django_tenant_apikeys.core.authenticate_key`,
    the same function the DRF backend uses, so both frameworks enforce
    identical rules: active, unexpired, allowed environment, ``allowed_ips``,
    and the model's ``is_tenant_allowed()`` hook. ``record_usage()`` is
    called and ``request.tenant`` is attached if the resolved model has a
    ``tenant`` relation.

    A key that fails to authenticate (unknown, tampered, inactive, expired)
    makes ``authenticate()`` return ``None``, which Ninja turns into a 401. A
    *valid* key refused by a policy (wrong environment, IP not allowed,
    tenant not allowed) or lacking a required scope raises ``HttpError(403)``
    instead -- the same 401/403 split the DRF backend makes.

    Pass ``scopes`` to require them on every operation using this instance;
    a key must have all of them::

        from ninja import NinjaAPI
        from django_tenant_apikeys.ninja import TenantAPIKeyAuth

        api = NinjaAPI(auth=TenantAPIKeyAuth())

        @api.get("/orders", auth=TenantAPIKeyAuth(scopes=["orders:read"]))
        def list_orders(request):
            return request.tenant.orders.all()

    Resolves the model from ``TENANT_API_KEY_MODEL`` by default; set
    ``model`` on a subclass to skip the setting, same as the DRF class::

        class PartnerAPIKeyAuth(TenantAPIKeyAuth):
            model = PartnerAPIKey

    Rate limiting is a Ninja throttle: see :class:`TenantAPIKeyThrottle`.
    """

    param_name = "Authorization"
    openapi_scheme = "apikey"
    model: type[AbstractTenantAPIKey] | None = None

    def __init__(self, scopes: Sequence[str] | None = None) -> None:
        if isinstance(scopes, str):
            raise TypeError("scopes must be a list of strings, not a single string")
        self.scopes: list[str] = list(scopes or [])
        super().__init__()

    def get_model(self) -> type[AbstractTenantAPIKey]:
        return self.model or get_api_key_model()

    def authenticate(self, request: HttpRequest, key: str | None) -> AbstractTenantAPIKey | None:
        if not key:
            return None

        parts = key.split()
        if len(parts) != 2 or parts[0].lower() != API_KEY_KEYWORD.lower():
            return None

        try:
            api_key = authenticate_key(
                parts[1], model=self.get_model(), client_ip=get_client_ip(request)
            )
        except APIKeyRejected as exc:
            if exc.is_policy_violation:
                raise HttpError(403, client_message(exc.reason)) from exc
            return None

        if not all(api_key.has_scope(scope) for scope in self.scopes):
            raise HttpError(403, MISSING_SCOPE_MESSAGE)

        if hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant  # type: ignore[attr-defined]

        return api_key


try:
    from ninja.throttling import BaseThrottle as _NinjaBaseThrottle
except ImportError:  # pragma: no cover - django-ninja < 1.2 has no throttling
    pass
else:
    __all__.append("TenantAPIKeyThrottle")

    class TenantAPIKeyThrottle(_NinjaBaseThrottle):
        """Enforces the authenticated key's ``rate_limit`` as a Ninja throttle
        (needs ``django-ninja >= 1.2``). Ninja answers 429 with ``Retry-After``::

            api = NinjaAPI(auth=TenantAPIKeyAuth(), throttle=[TenantAPIKeyThrottle()])

        Setting it on the ``NinjaAPI`` (or a router) applies it to every
        operation beneath it, so no endpoint can forget it. Throttles run
        after authentication; a request that isn't authenticated by an API
        key isn't this throttle's concern and is always allowed.
        """

        def __init__(self) -> None:
            # Ninja builds one throttle instance per operation and shares it
            # across requests, so the last result can't live on ``self``.
            self._local = threading.local()

        def allow_request(self, request: HttpRequest) -> bool:
            api_key = getattr(request, "auth", None)
            if not isinstance(api_key, AbstractTenantAPIKey):
                return True
            result: RateLimitResult = check_rate_limit(api_key)
            self._local.result = result
            return result.allowed

        def wait(self) -> float | None:
            result: RateLimitResult | None = getattr(self._local, "result", None)
            return None if result is None or result.retry_after is None else result.retry_after
