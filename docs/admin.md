# Django admin integration

```python
# myapp/admin.py
from django.contrib import admin
from django_tenant_apikeys.admin import TenantAPIKeyAdmin
from myapp.models import OrganizationAPIKey


@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    pass
```

That gets you a list view with a masked key column, an environment column,
a computed status column, and a bulk revoke action — without writing any of
it yourself.

## The one-time secret reveal

Stripe, GitHub, and AWS all show you a new secret exactly once, at creation,
and never again. That's a direct consequence of only ever storing a hash:
if the admin could show the secret later, it would mean the secret was
retrievable from the database, which defeats the point of hashing it.
`TenantAPIKeyAdmin.save_model()` implements the same pattern:

```python
def save_model(self, request, obj, form, change):
    if change:
        super().save_model(request, obj, form, change)
        return

    full_key, key_prefix, hashed_key = generate_api_key()
    obj.prefix = key_prefix
    obj.hashed_key = hashed_key
    super().save_model(request, obj, form, change)

    self.message_user(request, self._one_time_key_message(full_key), level=messages.WARNING)
```

The `change` branch matters as much as the create branch — **editing an
existing key never regenerates it.** Without that check, renaming a key or
flipping `is_active` in the admin would silently mint a new secret and
invalidate whatever the client already has.

On create, `generate_api_key()` runs server-side, ignoring whatever the
submitted form contained. The raw key is shown exactly once, in a
dismissible warning message right after you save — `message_user()` with
Django's messages framework, not a custom template, so it survives the
redirect after save and gets styled by whatever admin theme you're running.
It's built with `format_html`, which HTML-escapes its arguments, so nothing
in the generated key can break out of the `<code>` tag it renders inside.

There's no "view secret" action afterward, by design. If you lose it before
copying it, the fix is [rotating](key-lifecycle.md#rotating-a-key-without-downtime)
the key, not digging through the database.

## What's masked, and what's read-only

```python
@admin.display(description="Key")
def masked_key(self, obj: AbstractTenantAPIKey) -> str:
    return f"{obj.prefix}.{'•' * 12}"
```

The list view never renders anything derived from `hashed_key` — `prefix`
plus a fixed run of bullet characters, which is enough to recognize *which*
key a row is without exposing anything secret.

`readonly_fields` covers `prefix`, `hashed_key`, `created_at`,
`last_used_at`, `revoked_at`, and `revoked_reason` — on the individual
change form, these render as plain text, not inputs. There's no form field
an admin user could tamper with to make the row accept an attacker-chosen
hash, or backdate `created_at`, or forge `revoked_at`.

## The status column

```python
@admin.display(description="Status")
def status(self, obj: AbstractTenantAPIKey) -> str:
    if obj.is_expired:
        return "Expired"
    if not obj.is_active:
        return "Revoked" if obj.revoked_at else "Inactive"
    return "Active"
```

`Revoked` only shows once `revoke()` has actually run (it sets
`revoked_at`) — distinct from `Inactive`, which is what an admin user
unchecking the "active" checkbox directly produces. `Expired` takes
precedence over both, since an expired-but-still-`is_active` key is
unusable either way.

## Bulk revocation

A **Revoke selected API keys** admin action is registered by default —
select rows in the list view, revoke them all with
`reason="revoked via admin"`, skipping any that are already inactive.

## Editable fields

`rate_limit`, `rate_limit_window`, `allowed_ips`, `metadata`, `environment`,
`scopes`, `name`, and `expires_at` are all ordinary editable fields on the
change form — nothing about them needed a custom widget. `allowed_ips` and
`metadata` render as Django's standard `JSONField` form widget (a validated
JSON textarea), the same as `scopes` already did before 0.4.0.

## Filtering and searching

```python
list_display = ("name", "masked_key", "environment", "status", "created_at", "expires_at", "last_used_at")
list_filter = ("is_active", "environment", "created_at", "expires_at")
search_fields = ("name", "prefix")
```

## Extending it for your concrete model

`TenantAPIKeyAdmin` is meant to be subclassed, not used directly. Extend
`list_display`/`list_filter` rather than replacing them, to keep the masked
key column and the readonly protections intact:

```python
@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    list_filter = TenantAPIKeyAdmin.list_filter + ("tenant",)
```

It's a normal `ModelAdmin` underneath — `fieldsets`, custom permissions,
inline models, all of that layers on top the way you'd expect from any
other `ModelAdmin` subclass.

## Next

- [Key lifecycle](key-lifecycle.md) — rotating and revoking from a script or
  the shell, not just the admin.
- [Management commands](management-commands.md) — the same operations,
  without opening the admin at all.
