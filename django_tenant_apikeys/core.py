"""The one place an API key is authenticated.

Both the Django REST Framework backend and the Django Ninja backend call
:func:`authenticate_key` and only translate its outcome into their own
framework's response, so a rule enforced here is enforced identically for
both -- there's no second copy to forget to update.

The checks run in this order, cheapest and least-informative first::

    shape -> lookup by prefix -> constant-time secret check
          -> active -> expired -> environment -> IP allowlist
          -> tenant hook -> record usage

Every failure raises :class:`APIKeyRejected` carrying a
:class:`RejectionReason`. The reason is logged and sent on the
``api_key_rejected`` signal; what a *client* is told is up to the adapter
(and never distinguishes "no such key" from "wrong secret").
"""

from __future__ import annotations

import enum
import logging
from typing import NoReturn

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist

from .models import _MAX_KEY_PREFIX_LENGTH, AbstractTenantAPIKey, get_api_key_model
from .signals import api_key_rejected, send_safely

__all__ = [
    "API_KEY_KEYWORD",
    "MISSING_SCOPE_MESSAGE",
    "POLICY_REASONS",
    "APIKeyRejected",
    "RejectionReason",
    "authenticate_key",
    "client_message",
    "split_raw_key",
]

logger = logging.getLogger("django_tenant_apikeys")

#: The ``Authorization`` scheme both integrations respond to.
API_KEY_KEYWORD = "Api-Key"

# The one convention this package has about tenancy: a relation named this.
_TENANT_FIELD: str = "tenant"

# A generated key is at most 32 (prefix) + 1 + 43 (token_urlsafe(32)) = 76
# characters; anything much longer than that can't be one of ours.
_MAX_RAW_KEY_LENGTH = 128


class RejectionReason(str, enum.Enum):
    """Why :func:`authenticate_key` refused a key. Values are stable strings
    suitable for log filters and metrics labels."""

    MALFORMED = "malformed"
    UNKNOWN_KEY = "unknown_key"
    BAD_SECRET = "bad_secret"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    ENVIRONMENT = "environment"
    IP_NOT_ALLOWED = "ip_not_allowed"
    TENANT_NOT_ALLOWED = "tenant_not_allowed"


#: Rejections where the key *itself* is valid and being refused by a policy
#: (adapters answer 403), as opposed to failing authentication (401).
POLICY_REASONS = frozenset(
    {
        RejectionReason.ENVIRONMENT,
        RejectionReason.IP_NOT_ALLOWED,
        RejectionReason.TENANT_NOT_ALLOWED,
    }
)


#: What a client is told for each reason that isn't a bare "Invalid API key."
#: (malformed, unknown key and wrong secret never reveal which one it was).
#: These are only reachable once the secret has verified, so they're shown to
#: the key's legitimate holder, not to someone guessing.
_CLIENT_MESSAGES = {
    RejectionReason.INACTIVE: "This API key has been deactivated.",
    RejectionReason.EXPIRED: "This API key has expired.",
    RejectionReason.ENVIRONMENT: "This API key can't be used in this environment.",
    RejectionReason.IP_NOT_ALLOWED: "This IP address is not permitted to use this API key.",
    RejectionReason.TENANT_NOT_ALLOWED: "This API key's tenant is not permitted to use the API.",
}

MISSING_SCOPE_MESSAGE = "This API key does not have the required scope(s) for this action."


def client_message(reason: RejectionReason) -> str:
    """The response message an adapter should send for ``reason``."""
    return _CLIENT_MESSAGES.get(reason, "Invalid API key.")


class APIKeyRejected(Exception):
    """Raised by :func:`authenticate_key`. ``api_key`` is the matched key
    once the lookup has found one (``None`` for ``MALFORMED``/``UNKNOWN_KEY``)."""

    def __init__(self, reason: RejectionReason, api_key: AbstractTenantAPIKey | None = None):
        super().__init__(reason.value)
        self.reason = reason
        self.api_key = api_key

    @property
    def is_policy_violation(self) -> bool:
        return self.reason in POLICY_REASONS


def split_raw_key(raw_key: str) -> tuple[str, str] | None:
    """``(prefix, secret)`` if ``raw_key`` has the shape of a generated key,
    else ``None``. Checked before any database query so oversized, empty,
    control-character or whitespace-laden input from an unauthenticated
    caller never reaches the ORM."""
    if not raw_key or len(raw_key) > _MAX_RAW_KEY_LENGTH:
        return None
    if not raw_key.isprintable() or any(char.isspace() for char in raw_key):
        return None
    prefix, dot, secret = raw_key.partition(".")
    if not dot or not prefix or not secret or len(prefix) > _MAX_KEY_PREFIX_LENGTH:
        return None
    return prefix, secret


def _tenant_relation(model: type[AbstractTenantAPIKey]) -> bool:
    try:
        field = model._meta.get_field(_TENANT_FIELD)
    except FieldDoesNotExist:
        return False
    return bool(field.is_relation and (field.many_to_one or field.one_to_one))


def _reject(
    model: type[AbstractTenantAPIKey],
    reason: RejectionReason,
    api_key: AbstractTenantAPIKey | None,
    client_ip: str,
) -> NoReturn:
    # ``prefix`` is only logged once it matched a real row: for a malformed
    # or unknown key the "prefix" is just attacker-supplied text (and, for a
    # key pasted without its dot, could be the entire secret).
    logger.warning(
        "API key rejected: reason=%s prefix=%s client_ip=%r",
        reason.value,
        api_key.prefix if api_key is not None else "-",
        client_ip[:64],
    )
    send_safely(
        api_key_rejected, model, reason=reason.value, api_key=api_key, client_ip=client_ip
    )
    raise APIKeyRejected(reason, api_key)


def authenticate_key(
    raw_key: str,
    *,
    model: type[AbstractTenantAPIKey] | None = None,
    client_ip: str = "",
) -> AbstractTenantAPIKey:
    """Return the key ``raw_key`` authenticates as, or raise
    :class:`APIKeyRejected`.

    ``model`` defaults to ``TENANT_API_KEY_MODEL``. ``client_ip`` is the
    caller's address (see :func:`django_tenant_apikeys.ip.get_client_ip`);
    leave it empty if unknown -- a key with ``allowed_ips`` set then fails
    closed rather than being waved through.

    Settings read here: ``TENANT_API_KEY_ALLOWED_ENVIRONMENTS`` (if set, a
    key's ``environment`` must be one of them) and ``TENANT_API_KEY_RECORD_IP``
    (store ``last_used_ip``).
    """
    if model is None:
        model = get_api_key_model()

    parts = split_raw_key(raw_key)
    if parts is None:
        _reject(model, RejectionReason.MALFORMED, None, client_ip)

    queryset = model.objects.all()
    if _tenant_relation(model):
        # One JOIN now instead of a second query when the adapter reads
        # ``api_key.tenant`` to set ``request.tenant``.
        queryset = queryset.select_related(_TENANT_FIELD)
    try:
        api_key: AbstractTenantAPIKey = queryset.get(prefix=parts[0])
    except model.DoesNotExist:
        _reject(model, RejectionReason.UNKNOWN_KEY, None, client_ip)

    if not api_key.verify_key(raw_key):
        _reject(model, RejectionReason.BAD_SECRET, api_key, client_ip)
    if not api_key.is_active:
        _reject(model, RejectionReason.INACTIVE, api_key, client_ip)
    if api_key.is_expired:
        _reject(model, RejectionReason.EXPIRED, api_key, client_ip)

    allowed_environments = getattr(settings, "TENANT_API_KEY_ALLOWED_ENVIRONMENTS", None)
    if allowed_environments is not None and api_key.environment not in allowed_environments:
        _reject(model, RejectionReason.ENVIRONMENT, api_key, client_ip)
    if not api_key.is_ip_allowed(client_ip):
        _reject(model, RejectionReason.IP_NOT_ALLOWED, api_key, client_ip)
    if not api_key.is_tenant_allowed():
        _reject(model, RejectionReason.TENANT_NOT_ALLOWED, api_key, client_ip)

    record_ip = getattr(settings, "TENANT_API_KEY_RECORD_IP", False)
    api_key.record_usage(ip=client_ip if record_ip else None)
    return api_key
