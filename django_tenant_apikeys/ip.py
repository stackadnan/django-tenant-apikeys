"""Client IP resolution, shared by the DRF and Ninja integrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from django.http import HttpRequest

__all__ = ["get_client_ip"]


def get_client_ip(request: HttpRequest) -> str:
    """Best-effort client IP for ``request``, for use with
    ``AbstractTenantAPIKey.is_ip_allowed()``.

    Returns ``REMOTE_ADDR`` unless ``settings.TENANT_API_KEY_TRUSTED_PROXY_HEADER``
    names a ``request.META`` key to prefer instead (e.g. ``"HTTP_X_FORWARDED_FOR"``).
    That's opt-in on purpose -- ``X-Forwarded-For`` and friends are ordinary
    request headers, trivially spoofable by any client, and only mean
    anything if a proxy you control is the one setting them and stripping
    whatever a client sent. Leaving the setting unset (the default) means
    this always reads the connection's actual source address.

    When the header is trusted, only its first entry is used -- the address
    nearest the client, assuming a single reverse proxy in front of Django.
    A chain of multiple trusted proxies isn't handled here; set
    ``REMOTE_ADDR``-equivalent trust up further up your stack if you need
    that.
    """
    header = getattr(settings, "TENANT_API_KEY_TRUSTED_PROXY_HEADER", None)
    if header:
        forwarded: str | None = request.META.get(header)
        if forwarded:
            return forwarded.split(",")[0].strip()
    remote_addr: str = request.META.get("REMOTE_ADDR", "")
    return remote_addr
