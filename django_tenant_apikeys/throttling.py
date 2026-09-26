"""Django REST Framework throttle enforcing a key's own ``rate_limit``."""

from __future__ import annotations

try:
    from rest_framework.request import Request
    from rest_framework.throttling import BaseThrottle
    from rest_framework.views import APIView
except ImportError as exc:  # pragma: no cover - exercised only when DRF is absent
    raise ImportError(
        "django-tenant-apikeys requires djangorestframework to use "
        "TenantAPIKeyThrottle. Install it with `pip install django-tenant-apikeys[drf]`."
    ) from exc

from .models import AbstractTenantAPIKey
from .ratelimit import RateLimitResult, check_rate_limit

__all__ = ["TenantAPIKeyThrottle"]


class TenantAPIKeyThrottle(BaseThrottle):
    """Enforces the authenticated key's ``rate_limit``, if any.

    A regular DRF throttle, so DRF does the rest: a 429 with ``Retry-After``,
    and the usual ways of applying it -- set it once for every view::

        REST_FRAMEWORK = {
            "DEFAULT_THROTTLE_CLASSES": [
                "django_tenant_apikeys.throttling.TenantAPIKeyThrottle",
            ],
        }

    or per view with ``throttle_classes``. A key with no ``rate_limit`` is
    never throttled, and a request not authenticated by an API key isn't this
    throttle's concern (it's allowed -- combine with DRF's own throttles for
    those).

    Also sets ``X-RateLimit-Limit``/``-Remaining``/``-Reset`` on the response,
    allowed or not, via ``view.headers`` -- the mechanism DRF itself uses for
    headers like ``Allow``.

    Replaces :class:`~django_tenant_apikeys.permissions.WithinRateLimit`,
    which is a permission class doing a throttle's job.
    """

    def __init__(self) -> None:
        # DRF builds a fresh throttle per request, so this is per-request.
        self._result: RateLimitResult | None = None

    def allow_request(self, request: Request, view: APIView) -> bool:
        api_key = request.auth
        if not isinstance(api_key, AbstractTenantAPIKey):
            return True
        result = check_rate_limit(api_key)
        self._result = result
        if result.limit is not None:
            view.headers["X-RateLimit-Limit"] = str(result.limit)
            view.headers["X-RateLimit-Remaining"] = str(result.remaining)
            view.headers["X-RateLimit-Reset"] = str(result.reset_at)
        return result.allowed

    def wait(self) -> float | None:
        return None if self._result is None else self._result.retry_after
