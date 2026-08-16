"""Django REST Framework authentication backend for django-tenant-apikeys."""

from __future__ import annotations

from django.utils import timezone

try:
    from rest_framework import exceptions
    from rest_framework.authentication import BaseAuthentication, get_authorization_header
    from rest_framework.request import Request
except ImportError as exc:  # pragma: no cover - exercised only when DRF is absent
    raise ImportError(
        "django-tenant-apikeys requires djangorestframework to use "
        "TenantAPIKeyAuthentication. Install it with "
        "`pip install django-tenant-apikeys[drf]`."
    ) from exc

from .models import AbstractTenantAPIKey, get_api_key_model

#: Re-exported for convenience/backward compatibility -- the canonical
#: definition lives in :mod:`django_tenant_apikeys.models` since it is
#: needed by non-DRF integrations (e.g. Django Ninja) too.
__all__ = ["API_KEY_KEYWORD", "TenantAPIKeyAuthentication", "get_api_key_model"]

#: The ``Authorization`` header scheme this backend responds to, e.g.
#: ``Authorization: Api-Key <raw_key>``.
API_KEY_KEYWORD = "Api-Key"


class TenantAPIKeyAuthentication(BaseAuthentication):
    """Authenticate requests bearing an ``Authorization: Api-Key <key>`` header.

    On success, returns ``(None, api_key_instance)``: the first element of
    DRF's ``(user, auth)`` tuple is intentionally ``None`` rather than a
    Django ``User``, since an API key authenticates a tenant/client
    integration, not a human account. The authenticated key is available as
    ``request.auth`` in views, e.g. for :class:`~django_tenant_apikeys.permissions.HasAPIKeyScope`.

    If the resolved model defines a ``tenant`` relation, the related object
    is additionally attached to the request as ``request.tenant``.

    The model is resolved from ``settings.TENANT_API_KEY_MODEL`` by default.
    Subclass and set the ``model`` attribute directly to bypass the setting,
    e.g. when a project needs multiple key models authenticated differently::

        class PartnerAPIKeyAuthentication(TenantAPIKeyAuthentication):
            model = PartnerAPIKey
    """

    keyword = API_KEY_KEYWORD
    www_authenticate_realm = "api"
    model: type[AbstractTenantAPIKey] | None = None

    def get_model(self) -> type[AbstractTenantAPIKey]:
        return self.model or get_api_key_model()

    def authenticate(self, request: Request) -> tuple[None, AbstractTenantAPIKey] | None:
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth) == 1:
            raise exceptions.AuthenticationFailed(
                "Invalid Api-Key header. No credentials provided."
            )
        if len(auth) > 2:
            raise exceptions.AuthenticationFailed(
                "Invalid Api-Key header. Key string should not contain spaces."
            )

        try:
            raw_key = auth[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed(
                "Invalid Api-Key header. Key string should not contain invalid characters."
            ) from exc

        return self.authenticate_credentials(raw_key, request)

    def authenticate_credentials(
        self, raw_key: str, request: Request | None = None
    ) -> tuple[None, AbstractTenantAPIKey]:
        model = self.get_model()
        key_prefix, _sep, _secret = raw_key.partition(".")

        try:
            api_key = model.objects.get(prefix=key_prefix)
        except model.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("Invalid API key.") from exc

        if not api_key.verify_key(raw_key):
            raise exceptions.AuthenticationFailed("Invalid API key.")

        if not api_key.is_active:
            raise exceptions.AuthenticationFailed("This API key has been deactivated.")

        if api_key.expires_at is not None and api_key.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("This API key has expired.")

        if request is not None and hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant  # type: ignore[attr-defined]

        return None, api_key

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="{self.www_authenticate_realm}"'
