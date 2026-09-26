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
    anything if a proxy you control is the one setting them.

    Each trusted proxy *appends* the address of the peer it received the
    request from, so entries a client sent itself sit on the **left** and
    entries your own proxies added sit on the **right**. The client address
    your outermost trusted proxy saw is therefore the
    ``settings.TENANT_API_KEY_TRUSTED_PROXY_COUNT``-th entry from the right
    (default ``1``, i.e. the rightmost entry -- correct for one proxy in
    front of Django, whether it appends or overwrites the header). Set it to
    the number of trusted proxy hops in front of Django, e.g. ``2`` for
    ``client -> CDN -> load balancer -> Django``. Anything to the left of
    that entry is client-controlled and never used.

    If the header is missing, or has fewer entries than the configured
    proxy count (so the request can't have passed through every expected
    proxy), this falls back to ``REMOTE_ADDR``.
    """
    remote_addr: str = request.META.get("REMOTE_ADDR", "")
    header = getattr(settings, "TENANT_API_KEY_TRUSTED_PROXY_HEADER", None)
    if not header:
        return remote_addr
    forwarded: str | None = request.META.get(header)
    if not forwarded:
        return remote_addr
    count = getattr(settings, "TENANT_API_KEY_TRUSTED_PROXY_COUNT", 1)
    entries = [entry.strip() for entry in forwarded.split(",")]
    if count < 1 or len(entries) < count:
        return remote_addr
    return entries[-count]
