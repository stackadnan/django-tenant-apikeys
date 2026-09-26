"""Django REST Framework authentication backend for django-tenant-apikeys."""

from __future__ import annotations

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

from .core import API_KEY_KEYWORD, APIKeyRejected, authenticate_key, client_message
from .ip import get_client_ip
from .models import AbstractTenantAPIKey, get_api_key_model

# get_api_key_model is re-exported here too since non-DRF integrations
# (Ninja) need it without pulling in this module's DRF dependency.
__all__ = ["API_KEY_KEYWORD", "TenantAPIKeyAuthentication", "get_api_key_model"]


class TenantAPIKeyAuthentication(BaseAuthentication):
    """Authenticates ``Authorization: Api-Key <key>`` requests.

    Returns ``(None, api_key_instance)`` on success -- no Django ``User``,
    since a key authenticates an integration rather than a person. If the
    model has a ``tenant`` relation it's attached to ``request.tenant``.

    All verification and policy enforcement (active, expiry, environment,
    ``allowed_ips``, the tenant hook) lives in
    :func:`django_tenant_apikeys.core.authenticate_key`; this class only maps
    its outcome onto DRF: a key that fails to authenticate is a 401
    (``AuthenticationFailed``), a valid key refused by a policy is a 403
    (``PermissionDenied``). Because that happens during authentication, no
    view can accept a key and forget to check its IP allowlist.

    Resolves the model from ``TENANT_API_KEY_MODEL`` by default; set
    ``model`` on a subclass to skip the setting::

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
        # Without a request there's no client IP; a key restricted by
        # ``allowed_ips`` then fails closed.
        client_ip = get_client_ip(request) if request is not None else ""
        try:
            api_key = authenticate_key(raw_key, model=self.get_model(), client_ip=client_ip)
        except APIKeyRejected as exc:
            message = client_message(exc.reason)
            if exc.is_policy_violation:
                raise exceptions.PermissionDenied(message) from exc
            raise exceptions.AuthenticationFailed(message) from exc

        if request is not None and hasattr(api_key, "tenant"):
            request.tenant = api_key.tenant  # type: ignore[attr-defined]

        return None, api_key

    def authenticate_header(self, request: Request) -> str:
        return f'{self.keyword} realm="{self.www_authenticate_realm}"'
