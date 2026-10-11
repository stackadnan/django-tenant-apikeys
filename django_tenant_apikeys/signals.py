"""Lifecycle signals, so a project can build audit trails or notifications on
top of this package without it shipping an audit table or webhook system.

All four are plain :class:`django.dispatch.Signal` instances, sent with the
concrete key model as ``sender``:

``api_key_created``
    ``api_key`` -- sent by ``generate_key()`` (and so by ``rotate()``).
``api_key_revoked``
    ``api_key``, ``reason`` -- sent by ``revoke()``, once per actual
    revocation (a repeat call on an already-revoked key sends nothing).
``api_key_rotated``
    ``old_key``, ``new_key``, ``grace_period`` (``None`` for an immediate
    rotation) -- sent by ``rotate()`` after its transaction completes.
``api_key_rejected``
    ``reason`` (a :class:`~django_tenant_apikeys.core.RejectionReason`
    value), ``api_key`` (the matched key, or ``None`` if none matched),
    ``client_ip`` -- sent by ``authenticate_key()`` for every rejected
    request, by both the DRF and Django Ninja backends. This fires for
    unauthenticated traffic, so keep receivers cheap.
``api_key_rate_limited``
    ``api_key``, ``result`` (the
    :class:`~django_tenant_apikeys.ratelimit.RateLimitResult` that denied the
    request) -- sent by ``check_rate_limit()`` when a key's ``rate_limit``
    is exceeded, from both the DRF and Ninja throttles. Not sent for a
    request within the limit, or for a key with no ``rate_limit`` set.

They're sent synchronously. If you call ``generate_key()``, ``revoke()`` or
``rotate()`` inside an ``atomic()`` block that later rolls back, a receiver
has already run -- defer with ``transaction.on_commit`` inside the receiver
if that matters. A receiver that raises never breaks the operation that
sent the signal: the exception is logged (``django_tenant_apikeys`` logger)
and swallowed.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import Signal

__all__ = [
    "api_key_created",
    "api_key_rate_limited",
    "api_key_rejected",
    "api_key_revoked",
    "api_key_rotated",
]

logger = logging.getLogger("django_tenant_apikeys")

api_key_created = Signal()
api_key_revoked = Signal()
api_key_rotated = Signal()
api_key_rejected = Signal()
api_key_rate_limited = Signal()


def send_safely(signal: Signal, sender: type, **kwargs: Any) -> None:
    """``signal.send_robust()``, logging (rather than raising) any receiver
    error -- an audit hook that breaks must not break authentication."""
    for receiver, response in signal.send_robust(sender=sender, **kwargs):
        if isinstance(response, Exception):
            logger.error(
                "Signal receiver %r raised %r; ignoring it.",
                receiver,
                response,
                exc_info=response,
            )
