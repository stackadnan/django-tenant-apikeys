"""Core models and key-generation utilities for django-tenant-apikeys.

The security model follows the "prefix + secret" pattern used by most
production API key systems (Stripe, GitHub, etc.):

* A raw key is only ever shown to the caller once, at creation time. It is
  never stored anywhere, in any form other than its SHA-256 hash.
* The raw key is split into a public ``prefix`` (stored in cleartext, used
  as an indexed lookup column) and a ``secret`` (never stored, only ever
  compared by its hash). This lets :class:`AbstractTenantAPIKey.objects`
  find the right row with an indexed equality lookup on ``prefix`` before
  paying the cost of a constant-time hash comparison, instead of hashing
  every stored key on every request.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING, Any, TypeVar

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

__all__ = [
    "generate_api_key",
    "get_api_key_model",
    "hash_key",
    "AbstractTenantAPIKey",
    "TenantAPIKeyManager",
]

#: Number of random bytes used for the human-visible "secret prefix" segment.
#: Rendered as hex, so this yields twice as many characters (8 by default).
_SECRET_PREFIX_BYTES = 4

#: Number of random bytes used for the secret segment, before URL-safe
#: base64 encoding. 32 bytes (256 bits) matches the SHA-256 hash strength
#: used to store the key and is comfortably beyond brute-force range.
_SECRET_BYTES = 32

#: Must match AbstractTenantAPIKey.prefix's max_length. generate_api_key()
#: validates against this so a long caller-supplied prefix fails loudly at
#: key-creation time instead of raising an opaque DataError (or silently
#: truncating, on backends that allow it) when the row is saved.
_MAX_KEY_PREFIX_LENGTH = 32

#: How much of that budget is consumed by the "_live_<secret_prefix>" suffix
#: generate_api_key() appends, leaving the rest for the caller-supplied
#: leading segment.
_MAX_INPUT_PREFIX_LENGTH = _MAX_KEY_PREFIX_LENGTH - len("_live_") - (_SECRET_PREFIX_BYTES * 2)

_KeyModel = TypeVar("_KeyModel", bound="AbstractTenantAPIKey")


def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of ``raw_key``.

    This is a plain (unsalted) hash. That is a deliberate trade-off, not an
    oversight: the input already carries 256 bits of cryptographic entropy
    (see :func:`generate_api_key`), so it is not vulnerable to dictionary or
    rainbow-table attacks the way a low-entropy user password would be.
    Salting would only add the ability to look up a key by hash without
    also knowing the prefix, which this library never needs to do.
    """
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "tak") -> tuple[str, str, str]:
    """Generate a new, cryptographically random API key.

    Args:
        prefix: A short, stable identifier for the *kind* of key being
            issued (e.g. ``"tak"``, or a per-application prefix such as
            ``"acme"``). It becomes the leading segment of both the full
            key and the stored lookup prefix, which is useful for
            distinguishing key families at a glance and for tools like
            secret scanners.

    Returns:
        A 3-tuple of ``(full_key, key_prefix, hashed_key)``:

        * ``full_key`` -- the complete secret value, formatted as
          ``<prefix>_live_<secret_prefix>.<secret>``. Shown to the caller
          exactly once; never persisted.
        * ``key_prefix`` -- the ``<prefix>_live_<secret_prefix>`` segment
          only. Safe to store in cleartext and index on, since it carries
          no meaningful entropy on its own -- it exists purely so a stored
          key row can be looked up in O(1) without scanning and hashing
          every row in the table.
        * ``hashed_key`` -- the SHA-256 hex digest of ``full_key``, safe to
          persist and compare against on future requests.

    Raises:
        ValueError: If ``prefix`` is too long for the generated
            ``key_prefix`` to fit within :attr:`AbstractTenantAPIKey.prefix`'s
            ``max_length=32`` once the fixed ``_live_<secret_prefix>`` suffix
            is appended.
    """
    if len(prefix) > _MAX_INPUT_PREFIX_LENGTH:
        raise ValueError(
            f"prefix {prefix!r} is {len(prefix)} characters long, but must be at "
            f"most {_MAX_INPUT_PREFIX_LENGTH} so the generated key_prefix fits "
            f"within AbstractTenantAPIKey.prefix's max_length={_MAX_KEY_PREFIX_LENGTH}."
        )
    secret_prefix = secrets.token_hex(_SECRET_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    key_prefix = f"{prefix}_live_{secret_prefix}"
    full_key = f"{key_prefix}.{secret}"
    hashed_key = hash_key(full_key)
    return full_key, key_prefix, hashed_key


def get_api_key_model() -> type[AbstractTenantAPIKey]:
    """Resolve the concrete API key model configured via ``settings.TENANT_API_KEY_MODEL``.

    This is framework-agnostic: it underlies
    :class:`~django_tenant_apikeys.authentication.TenantAPIKeyAuthentication`
    for DRF, but is equally usable from a Django Ninja auth callable, a
    plain Django view, or a management command.

    Raises:
        ImproperlyConfigured: If the setting is unset, or does not point to
            a valid, installed ``"app_label.ModelName"`` model.
    """
    model_path = getattr(settings, "TENANT_API_KEY_MODEL", None)
    if not model_path:
        raise ImproperlyConfigured(
            "TENANT_API_KEY_MODEL is not set. Add a setting such as "
            'TENANT_API_KEY_MODEL = "myapp.APIKey" pointing at your concrete '
            "AbstractTenantAPIKey subclass."
        )
    try:
        return apps.get_model(model_path)
    except (LookupError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"TENANT_API_KEY_MODEL refers to model '{model_path}' that has not "
            "been installed, or is not a valid 'app_label.ModelName' string."
        ) from exc


if TYPE_CHECKING:
    # django-stubs models Manager/QuerySet as generic over the model they
    # belong to. Parameterizing the real runtime base class would require
    # every consumer of this package to call django_stubs_ext.monkeypatch()
    # first (plain Django's Manager isn't subscriptable at runtime), so the
    # generic parameter is only visible to type checkers via this branch;
    # `else` is what actually executes.
    _TenantAPIKeyManagerBase = models.Manager["AbstractTenantAPIKey"]
else:
    _TenantAPIKeyManagerBase = models.Manager


class TenantAPIKeyManager(_TenantAPIKeyManagerBase):
    """Manager providing lookup helpers on top of the ``prefix`` column."""

    def get_from_key(self, raw_key: str) -> AbstractTenantAPIKey:
        """Return the stored key row referenced by ``raw_key``.

        Only the ``prefix`` segment of ``raw_key`` is used for the lookup;
        this does **not** verify the secret. Callers must still call
        :meth:`AbstractTenantAPIKey.verify_key` on the returned instance
        before trusting it -- this method exists purely to turn an O(n)
        "hash every row" search into an O(1) indexed lookup.

        Raises:
            self.model.DoesNotExist: If no row has a matching prefix.
        """
        key_prefix, _sep, _secret = raw_key.partition(".")
        return self.get(prefix=key_prefix)

    def get_usable_keys(self) -> models.QuerySet[AbstractTenantAPIKey]:
        """Return active, non-expired keys, ordered as :attr:`Meta.ordering`."""
        now = timezone.now()
        # django-stubs' mypy plugin doesn't propagate the manager's generic
        # parameter through this particular chained .filter().filter() call,
        # so it infers Any here despite both filter() calls being properly
        # typed in isolation -- a known class of rough edge in the plugin,
        # not a real type hole (get_from_key, right above, chains cleanly).
        return self.filter(is_active=True).filter(  # type: ignore[no-any-return]
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )


class AbstractTenantAPIKey(models.Model):
    """Abstract base model for a tenant-scoped API key.

    Host projects subclass this to attach a key to their own tenant model::

        class OrganizationAPIKey(AbstractTenantAPIKey):
            tenant = models.ForeignKey(
                "myapp.Organization",
                related_name="api_keys",
                on_delete=models.CASCADE,
            )

    Only the SHA-256 hash of a generated key is ever persisted -- the raw
    secret exists only in memory for the duration of :meth:`generate_key`
    and must be captured and shown to the caller by application code at
    that point, since it cannot be recovered afterwards.
    """

    name = models.CharField(
        max_length=100,
        help_text=_("A human-readable label to identify this key, e.g. its purpose or owner."),
    )
    prefix = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        editable=False,
        help_text=_("Public, non-secret identifier used to look up this key."),
    )
    hashed_key = models.CharField(
        max_length=128,
        editable=False,
        help_text=_("SHA-256 hash of the full secret key. The raw key itself is never stored."),
    )
    scopes = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            'Permission scopes granted to this key, e.g. ["orders:read", "orders:write"]. '
            'Use ["*"] to grant every scope.'
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Unchecking this immediately revokes the key without deleting it."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Optional expiration timestamp. Leave blank for a key that never expires."),
    )

    objects = TenantAPIKeyManager()

    class Meta:
        abstract = True
        ordering = ("-created_at",)
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: prefix={self.prefix!r}>"

    @classmethod
    def generate_key(
        cls: type[_KeyModel], *, prefix: str = "tak", **kwargs: Any
    ) -> tuple[_KeyModel, str]:
        """Create, save, and return a new key instance together with its raw secret.

        Args:
            prefix: Passed through to :func:`generate_api_key`.
            **kwargs: Any other concrete-model field values (e.g. ``name``,
                ``scopes``, ``expires_at``, or a ``tenant`` relation defined
                by a subclass).

        Returns:
            A ``(instance, raw_key)`` tuple. ``raw_key`` is the only time
            the caller will ever see the secret in full -- it is not
            recoverable from ``instance`` afterwards, since only its hash
            is persisted.
        """
        full_key, key_prefix, hashed_key = generate_api_key(prefix=prefix)
        instance = cls(prefix=key_prefix, hashed_key=hashed_key, **kwargs)
        instance.save()
        return instance, full_key

    def verify_key(self, raw_key: str) -> bool:
        """Return ``True`` if ``raw_key`` hashes to this row's stored hash.

        Uses :func:`secrets.compare_digest` for a constant-time comparison,
        so response timing cannot be used to leak how much of a guessed key
        was correct.
        """
        return secrets.compare_digest(self.hashed_key, hash_key(raw_key))

    @property
    def is_expired(self) -> bool:
        """``True`` if this key has an ``expires_at`` in the past."""
        return self.expires_at is not None and self.expires_at < timezone.now()

    @property
    def is_valid(self) -> bool:
        """``True`` if this key is active and not expired."""
        return self.is_active and not self.is_expired

    def has_scope(self, required_scope: str) -> bool:
        """Return ``True`` if this key's ``scopes`` satisfy ``required_scope``.

        Three forms of match are supported, checked in order:

        1. Exact match -- ``required_scope`` appears verbatim in ``scopes``.
        2. Global wildcard -- ``scopes`` contains ``"*"``, granting every
           possible scope.
        3. Namespaced wildcard -- ``scopes`` contains an entry ending in
           ``":*"`` (e.g. ``"orders:*"``) whose namespace prefix matches
           ``required_scope`` (e.g. ``"orders:read"``).
        """
        if not self.scopes:
            return False
        if required_scope in self.scopes:
            return True
        if "*" in self.scopes:
            return True
        for scope in self.scopes:
            if isinstance(scope, str) and scope.endswith(":*"):
                namespace = scope[:-1]  # e.g. "orders:*" -> "orders:"
                if required_scope.startswith(namespace):
                    return True
        return False
