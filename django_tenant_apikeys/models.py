"""Core models and key-generation utilities for django-tenant-apikeys.

Keys use the standard prefix + secret pattern (Stripe, GitHub, etc.): the
prefix is a cleartext, indexed lookup value with no real entropy, and the
secret is only ever stored as a SHA-256 hash.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

__all__ = [
    "generate_api_key",
    "get_api_key_model",
    "hash_key",
    "AbstractTenantAPIKey",
    "Environment",
    "RateLimitWindow",
    "TenantAPIKeyManager",
]

_SECRET_PREFIX_BYTES = 4  # -> 8 hex chars
_SECRET_BYTES = 32  # 256 bits, matches the SHA-256 hash strength

# Must match AbstractTenantAPIKey.prefix.max_length. generate_api_key()
# checks against this so a long custom prefix fails with a clear error
# instead of a DB-level truncation/DataError at save time.
_MAX_KEY_PREFIX_LENGTH = 32
_MAX_INPUT_PREFIX_LENGTH = _MAX_KEY_PREFIX_LENGTH - len("_live_") - (_SECRET_PREFIX_BYTES * 2)

_KeyModel = TypeVar("_KeyModel", bound="AbstractTenantAPIKey")


class Environment(models.TextChoices):
    """Coarser than it looks -- only ``PRODUCTION`` and ``STAGING`` map to a
    ``_live_`` prefix, ``TEST`` and ``DEVELOPMENT`` both map to ``_test_``
    (see ``_ENVIRONMENT_PREFIX_SEGMENT``). The ``environment`` field is what
    application code should actually branch on; the prefix is just enough
    to eyeball a key's blast radius in a log line."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TEST = "test"


class RateLimitWindow(models.TextChoices):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


DEFAULT_ENVIRONMENT = Environment.PRODUCTION
DEFAULT_RATE_LIMIT_WINDOW = RateLimitWindow.MINUTE

# Every key minted before 0.4.0 used a hardcoded "_live_" segment, so
# PRODUCTION (the default for keys with no explicit environment) and
# STAGING both keep that segment -- only TEST/DEVELOPMENT switch to
# "_test_". Both segments are 4 letters, so this doesn't change
# _MAX_INPUT_PREFIX_LENGTH's arithmetic below.
_ENVIRONMENT_PREFIX_SEGMENT = {
    Environment.PRODUCTION: "live",
    Environment.STAGING: "live",
    Environment.DEVELOPMENT: "test",
    Environment.TEST: "test",
}


_GENERATED_PREFIX_RE = re.compile(r"^(?P<base>.+)_(?:live|test)_[0-9a-f]{8}$")


def _base_prefix(key_prefix: str) -> str:
    """The caller-chosen ``prefix`` a stored ``key_prefix`` was generated
    from (``"acme_live_3f9a2c1d"`` -> ``"acme"``), or the ``"tak"`` default
    if it doesn't look like a generated prefix. Lets ``rotate()`` keep a
    key's custom prefix instead of silently resetting it."""
    match = _GENERATED_PREFIX_RE.match(key_prefix)
    return match.group("base") if match else "tak"


def hash_key(raw_key: str) -> str:
    """SHA-256 hex digest of ``raw_key``. Unsalted on purpose -- the input
    already has 256 bits of entropy, so it isn't at risk the way a
    low-entropy password hash would be."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(
    prefix: str = "tak", *, environment: str = DEFAULT_ENVIRONMENT
) -> tuple[str, str, str]:
    """Generate a random key and return ``(full_key, key_prefix, hashed_key)``.

    ``full_key`` (``<prefix>_live_<secret_prefix>.<secret>`` or
    ``<prefix>_test_<secret_prefix>.<secret>``, depending on ``environment``)
    is shown once and never persisted. ``key_prefix`` is the part before the
    dot, safe to store and index on. ``hashed_key`` is what actually gets
    saved.

    Raises ``ValueError`` if ``prefix`` is too long to fit the generated
    ``key_prefix`` within ``AbstractTenantAPIKey.prefix``'s ``max_length=32``,
    or if ``environment`` isn't one of the ``Environment`` values.
    """
    if len(prefix) > _MAX_INPUT_PREFIX_LENGTH:
        raise ValueError(
            f"prefix {prefix!r} is {len(prefix)} characters long, but must be at "
            f"most {_MAX_INPUT_PREFIX_LENGTH} so the generated key_prefix fits "
            f"within AbstractTenantAPIKey.prefix's max_length={_MAX_KEY_PREFIX_LENGTH}."
        )
    try:
        segment = _ENVIRONMENT_PREFIX_SEGMENT[environment]
    except KeyError:
        raise ValueError(
            f"environment must be one of {Environment.values}, got {environment!r}"
        ) from None
    secret_prefix = secrets.token_hex(_SECRET_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    key_prefix = f"{prefix}_{segment}_{secret_prefix}"
    full_key = f"{key_prefix}.{secret}"
    hashed_key = hash_key(full_key)
    return full_key, key_prefix, hashed_key


def _validate_scopes(scopes: Any) -> None:
    """Raise ``ValueError`` if ``scopes`` isn't a list/tuple of non-empty strings.

    Called from :meth:`AbstractTenantAPIKey.generate_key`, the one blessed
    creation path, so a mistake like passing a bare string instead of a
    list is caught immediately rather than silently misbehaving later --
    e.g. ``scopes="orders:read"`` would otherwise iterate character by
    character in :meth:`~AbstractTenantAPIKey.has_scope`'s wildcard check.
    """
    if not isinstance(scopes, (list, tuple)):
        raise ValueError(f"scopes must be a list of strings, got {type(scopes).__name__}")
    for scope in scopes:
        if not isinstance(scope, str) or not scope:
            raise ValueError(f"each scope must be a non-empty string, got {scope!r}")


def _validate_allowed_ips(allowed_ips: Any) -> None:
    """Raise ``ValueError`` if ``allowed_ips`` isn't a list of individual IPs
    or CIDR networks (v4 or v6), parsed with ``ipaddress`` -- same reasoning
    as ``_validate_scopes``: catch a typo'd network at issuance time rather
    than have it silently never match anything in ``is_ip_allowed()``."""
    if not isinstance(allowed_ips, (list, tuple)):
        raise ValueError(
            f"allowed_ips must be a list of strings, got {type(allowed_ips).__name__}"
        )
    for entry in allowed_ips:
        if not isinstance(entry, str) or not entry:
            raise ValueError(f"each allowed_ips entry must be a non-empty string, got {entry!r}")
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(
                f"{entry!r} is not a valid IP address or CIDR network"
            ) from None


def _validate_rate_limit(rate_limit: Any, window: Any) -> None:
    """Raise ``ValueError`` for a non-positive ``rate_limit`` or a ``window``
    outside ``RateLimitWindow``. No-op if ``rate_limit`` is ``None`` --
    ``window`` is meaningless without a limit to apply it to."""
    if rate_limit is None:
        return
    if isinstance(rate_limit, bool) or not isinstance(rate_limit, int) or rate_limit <= 0:
        raise ValueError(f"rate_limit must be a positive integer, got {rate_limit!r}")
    if window not in RateLimitWindow.values:
        raise ValueError(
            f"rate_limit_window must be one of {RateLimitWindow.values}, got {window!r}"
        )


def get_api_key_model() -> type[AbstractTenantAPIKey]:
    """Resolve the model configured via ``settings.TENANT_API_KEY_MODEL``.

    Framework-agnostic -- used by the DRF authentication backend, but just
    as usable from a Ninja auth callable or a plain view. Raises
    ``ImproperlyConfigured`` if the setting is missing or invalid.
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
    # Real Manager isn't subscriptable at runtime without django_stubs_ext's
    # monkeypatch(), so the generic param only exists for type checkers.
    _TenantAPIKeyManagerBase = models.Manager["AbstractTenantAPIKey"]
else:
    _TenantAPIKeyManagerBase = models.Manager


class TenantAPIKeyManager(_TenantAPIKeyManagerBase):
    """Manager with lookup helpers on top of the ``prefix`` column."""

    def get_from_key(self, raw_key: str) -> AbstractTenantAPIKey:
        """Indexed prefix lookup for ``raw_key``. Doesn't verify the secret
        -- call ``verify_key()`` on the result. Raises ``DoesNotExist`` if
        no row matches."""
        key_prefix, _sep, _secret = raw_key.partition(".")
        return self.get(prefix=key_prefix)

    def get_usable_keys(self) -> models.QuerySet[AbstractTenantAPIKey]:
        """Active, unexpired keys."""
        now = timezone.now()
        # mypy infers Any through this chained filter() under django-stubs;
        # get_from_key above types fine, so this looks like a plugin quirk
        # rather than an actual hole.
        return self.filter(is_active=True).filter(  # type: ignore[no-any-return]
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )


class AbstractTenantAPIKey(models.Model):
    """Abstract base model for a tenant-scoped API key.

    Subclass it and add your own tenant relation::

        class OrganizationAPIKey(AbstractTenantAPIKey):
            tenant = models.ForeignKey(
                "myapp.Organization",
                related_name="api_keys",
                on_delete=models.CASCADE,
            )
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
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=DEFAULT_ENVIRONMENT,
        help_text=_(
            "What this key is meant to be used against. Authoritative -- unlike the "
            "_live_/_test_ segment in the key's prefix, this is what application code "
            "should actually check."
        ),
    )
    rate_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "Maximum requests this key may make per rate_limit_window. Leave blank "
            "for no rate limiting."
        ),
    )
    rate_limit_window = models.CharField(
        max_length=10,
        choices=RateLimitWindow.choices,
        default=DEFAULT_RATE_LIMIT_WINDOW,
        help_text=_("Window rate_limit is counted over. Ignored unless rate_limit is set."),
    )
    allowed_ips = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            "IPs and/or CIDR networks this key may be used from, e.g. "
            '["203.0.113.10", "203.0.113.0/24"]. Leave blank to allow any IP.'
        ),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Arbitrary application-defined data attached to this key, e.g. "
            '{"service": "billing", "owner": "payments-team"}. Not interpreted '
            "by this library."
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
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text=_("When this key last authenticated a request. Updated by record_usage()."),
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text=_("When this key was revoked, if it has been. Set by revoke()."),
    )
    revoked_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        editable=False,
        help_text=_("Why this key was revoked, if a reason was given to revoke()."),
    )

    objects = TenantAPIKeyManager()

    #: Minimum gap between last_used_at writes. record_usage() is a no-op if
    #: the key was already marked used more recently than this, so a hot
    #: endpoint doesn't turn every authenticated request into a write.
    #: Override on a subclass for coarser or finer tracking.
    LAST_USED_THRESHOLD: ClassVar[timedelta] = timedelta(minutes=5)

    #: Fields never copied onto the new row by rotate() -- identity, secret
    #: material, and per-row audit/lifecycle state all have to be fresh.
    _ROTATION_EXCLUDED_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"id", "prefix", "hashed_key", "created_at", "last_used_at", "revoked_at",
         "revoked_reason", "is_active"}
    )

    class Meta:
        abstract = True
        ordering = ("-created_at",)
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: prefix={self.prefix!r}>"

    def clean(self) -> None:
        """Model-level validation, so the same rules ``generate_key()`` applies
        also hold for the Django admin, model forms, and ``full_clean()``.

        ``scopes``, ``allowed_ips`` and ``rate_limit`` are free-form
        ``JSONField``/integer columns; without this, only keys created via
        ``generate_key()`` were checked. Subclasses overriding ``clean()``
        should call ``super().clean()``.
        """
        super().clean()
        errors: dict[str, str] = {}
        for field, validator, args in (
            ("scopes", _validate_scopes, (self.scopes,)),
            ("allowed_ips", _validate_allowed_ips, (self.allowed_ips,)),
            ("rate_limit", _validate_rate_limit, (self.rate_limit, self.rate_limit_window)),
        ):
            try:
                validator(*args)
            except ValueError as exc:
                errors[field] = str(exc)
        if errors:
            raise ValidationError(errors)

    @classmethod
    def generate_key(
        cls: type[_KeyModel], *, prefix: str = "tak", **kwargs: Any
    ) -> tuple[_KeyModel, str]:
        """Create and save a new key, returning ``(instance, raw_key)``.

        ``**kwargs`` are passed straight to the model constructor (``name``,
        ``scopes``, ``expires_at``, ``environment``, ``rate_limit``,
        ``allowed_ips``, ``metadata``, a ``tenant`` relation, etc). ``raw_key``
        is your only chance to see the secret -- it isn't recoverable from
        ``instance`` afterwards.

        Raises ``ValueError`` if ``scopes`` or ``allowed_ips`` is passed and
        isn't a list of non-empty strings, if ``rate_limit`` is passed and
        isn't a positive integer, or if ``rate_limit_window``/``environment``
        is passed and isn't one of their respective choices.
        """
        _validate_scopes(kwargs.get("scopes", []))
        _validate_allowed_ips(kwargs.get("allowed_ips", []))
        _validate_rate_limit(
            kwargs.get("rate_limit"), kwargs.get("rate_limit_window", DEFAULT_RATE_LIMIT_WINDOW)
        )
        environment = kwargs.get("environment", DEFAULT_ENVIRONMENT)
        full_key, key_prefix, hashed_key = generate_api_key(prefix=prefix, environment=environment)
        instance = cls(prefix=key_prefix, hashed_key=hashed_key, **kwargs)
        instance.save()
        return instance, full_key

    def verify_key(self, raw_key: str) -> bool:
        """Constant-time check of ``raw_key`` against the stored hash."""
        return secrets.compare_digest(self.hashed_key, hash_key(raw_key))

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired

    def revoke(self, *, reason: str = "") -> None:
        """Deactivate this key immediately and permanently.

        Sets the same ``is_active`` flag that authentication already checks
        -- there's no separate "revoked" enforcement path to keep in sync.
        ``revoked_at``/``revoked_reason`` are audit metadata only.

        Idempotent: revoking a key that's already revoked leaves its original
        ``revoked_at``/``revoked_reason`` untouched, so a repeated call (a
        second admin click, a re-run command) can't overwrite the audit
        trail of the first. ("Permanently" here means "until an explicit
        :meth:`reactivate`" -- reactivation is a deliberate, supported
        rollback, e.g. undoing a rotation that didn't deploy.)
        """
        if not self.is_active and self.revoked_at is not None:
            return
        self.is_active = False
        self.revoked_at = timezone.now()
        self.revoked_reason = reason
        self.save(update_fields=["is_active", "revoked_at", "revoked_reason"])

    def reactivate(self) -> None:
        """Undo :meth:`revoke`. Does not affect expiration -- reactivating
        a key whose ``expires_at`` has already passed leaves it just as
        unusable as before, since :attr:`is_valid` checks both."""
        self.is_active = True
        self.revoked_at = None
        self.revoked_reason = ""
        self.save(update_fields=["is_active", "revoked_at", "revoked_reason"])

    def rotate(
        self: _KeyModel, *, prefix: str | None = None, **overrides: Any
    ) -> tuple[_KeyModel, str]:
        """Replace this key with a new one, revoking this row in the process.

        Every concrete-model field (``name``, ``scopes``, ``expires_at``, a
        subclass's ``tenant`` relation, anything else) carries over to the
        new row unchanged unless overridden via ``**overrides`` -- rotation
        never needs to know what fields a subclass adds. This row is kept,
        not deleted, so the old key remains visible for audit/history; it's
        revoked with ``reason="rotated"`` and can never authenticate again.

        Returns ``(new_instance, raw_key)``, exactly like :meth:`generate_key`.

        The row is re-read under a ``SELECT ... FOR UPDATE`` lock inside the
        transaction, so a stale instance (loaded before another request or
        worker already rotated/revoked the key) or two concurrent rotations
        can't both succeed and leave two live replacements. Field values are
        copied from that fresh row, not from unsaved in-memory edits on
        ``self``. ``prefix`` defaults to the one this key was originally
        generated with (``"acme_live_..."`` rotates to ``"acme_live_..."``).

        Raises ``ValueError`` if this key is already inactive or expired --
        rotating a dead key would silently hand out working access from
        something that was deliberately (or automatically) shut off.
        """
        if prefix is None:
            prefix = _base_prefix(self.prefix)
        with transaction.atomic():
            current = type(self).objects.select_for_update().get(pk=self.pk)
            if not current.is_valid:
                raise ValueError(
                    "Cannot rotate an inactive or expired key. Issue a new key "
                    "with generate_key() instead if you want to grant fresh access."
                )
            kwargs = {
                field.name: getattr(current, field.name)
                for field in current._meta.fields
                if field.name not in self._ROTATION_EXCLUDED_FIELDS
            }
            # JSONField values (scopes, allowed_ips, metadata) -- copy them so
            # mutating the new key's copy in memory can't reach back and mutate
            # this row's too.
            kwargs["scopes"] = list(kwargs["scopes"])
            kwargs["allowed_ips"] = list(kwargs["allowed_ips"])
            kwargs["metadata"] = dict(kwargs["metadata"])
            kwargs.update(overrides)
            new_instance, raw_key = type(self).generate_key(prefix=prefix, **kwargs)
            current.revoke(reason="rotated")
        # Keep the caller's instance in step with what was just persisted.
        self.is_active = current.is_active
        self.revoked_at = current.revoked_at
        self.revoked_reason = current.revoked_reason
        return new_instance, raw_key

    def record_usage(self) -> None:
        """Mark this key as used just now, throttled by ``LAST_USED_THRESHOLD``.

        Skips the write entirely if ``last_used_at`` is already within the
        threshold, so calling this on every authenticated request (which is
        exactly what ``TenantAPIKeyAuthentication`` does) doesn't turn a hot
        endpoint into a write on every single call. Uses a targeted
        ``UPDATE`` via the manager rather than ``save()``, so it doesn't
        re-validate or re-save the rest of the row.
        """
        now = timezone.now()
        if self.last_used_at is not None and now - self.last_used_at < self.LAST_USED_THRESHOLD:
            return
        type(self).objects.filter(pk=self.pk).update(last_used_at=now)
        self.last_used_at = now

    def has_scope(self, required_scope: str) -> bool:
        """True if ``scopes`` grants ``required_scope`` -- exact match,
        global ``"*"``, or a namespaced ``"orders:*"`` wildcard."""
        # Fail closed on malformed data (e.g. a bare string written by a
        # fixture or a raw ORM call): ``in`` on a str is a substring test,
        # which would over-grant.
        if not isinstance(self.scopes, (list, tuple)) or not self.scopes:
            return False
        if required_scope in self.scopes:
            return True
        if "*" in self.scopes:
            return True
        for scope in self.scopes:
            if isinstance(scope, str) and scope.endswith(":*"):
                namespace = scope[:-1]  # "orders:*" -> "orders:"
                if required_scope.startswith(namespace):
                    return True
        return False

    def is_ip_allowed(self, client_ip: str) -> bool:
        """True if ``client_ip`` is covered by ``allowed_ips`` -- an exact
        address match or membership in a CIDR network. An empty
        ``allowed_ips`` means unrestricted (True for anything).

        ``client_ip`` and each ``allowed_ips`` entry are parsed with
        ``ipaddress``; a malformed ``client_ip`` never matches. A malformed
        ``allowed_ips`` entry is skipped rather than raising -- that
        shouldn't happen for a key created through ``generate_key()``
        (validated up front), but a row edited directly (e.g. a raw ORM
        call, a fixture) shouldn't be able to turn a restriction into an
        unhandled exception on every request.
        """
        if not self.allowed_ips:
            return True
        if not isinstance(self.allowed_ips, (list, tuple)):
            return False
        try:
            client = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        if isinstance(client, ipaddress.IPv6Address) and client.ipv4_mapped is not None:
            # A dual-stack socket reports IPv4 clients as ``::ffff:a.b.c.d``.
            client = client.ipv4_mapped
        for entry in self.allowed_ips:
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except (TypeError, ValueError):
                continue
            if client in network:
                return True
        return False
