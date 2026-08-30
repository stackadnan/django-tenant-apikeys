# One-time secret reveal in Django admin: the pattern behind `save_model`

Stripe, GitHub, and AWS all show you a new secret exactly once, at the
moment you create it, and never again. That's not a UI quirk — it's a
direct consequence of only ever storing a hash: if the admin panel could
show you the secret later, it would mean the secret (or something
equivalent to it) was retrievable from the database, which defeats the
point of hashing it in the first place. This page walks through how
`TenantAPIKeyAdmin` in
[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
implements that pattern.

## The three pieces

`TenantAPIKeyAdmin` combines three things to make "shown once, never
again" actually hold:

```python
list_display = ("name", "masked_key", "is_active", "created_at", "expires_at", "last_used_at")
readonly_fields = ("prefix", "hashed_key", "created_at", "last_used_at")

@admin.display(description="Key")
def masked_key(self, obj: AbstractTenantAPIKey) -> str:
    return f"{obj.prefix}.{'•' * 12}"
```

1. **`masked_key` in `list_display`** — the key list never renders
   anything from `hashed_key` at all, masked or otherwise. It shows the
   public `prefix` and a fixed run of bullet characters, which is enough
   to recognize *which* key a row is without exposing anything secret.
2. **`prefix` and `hashed_key` in `readonly_fields`** — even on the
   individual change form, these fields render as plain text, not
   inputs. There's no form field to tamper with to make the admin accept
   an attacker-chosen hash.
3. **`save_model`**, which does the actual generation and one-time
   display.

## Walking through `save_model`

```python
def save_model(self, request, obj, form, change):
    if change:
        super().save_model(request, obj, form, change)
        return

    full_key, key_prefix, hashed_key = generate_api_key()
    obj.prefix = key_prefix
    obj.hashed_key = hashed_key
    super().save_model(request, obj, form, change)

    self.message_user(
        request,
        self._one_time_key_message(full_key),
        level=messages.WARNING,
    )
```

The `change` branch matters as much as the create branch: **editing an
existing key never regenerates it.** If it didn't check `change` first,
renaming a key or flipping `is_active` in the admin would silently mint a
new secret and invalidate whatever the client already has — exactly the
kind of surprise rotation covered in
[Rotating and expiring API keys](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients).

On create, `generate_api_key()` is called server-side, ignoring whatever
the submitted form contained — `prefix` and `hashed_key` are `readonly_fields`
so the form doesn't even have real inputs for them, but the admin doesn't
rely on that alone; it overwrites `obj.prefix`/`obj.hashed_key` explicitly
before saving. Two independent reasons the value is trustworthy, not one.

`super().save_model()` is called *before* the message is queued, not after
— the object needs a real primary key first so the add-view's redirect
lands on the actual saved row, not a form re-render.

## Why the message, not the response body

`message_user(..., level=messages.WARNING)` uses Django's messages
framework rather than, say, putting the key in a custom template or a
flash banner you'd have to build yourself. That gets you a few things for
free: it survives the redirect after save (messages persist across one
redirect via session/cookie storage), it's styled as a warning by whatever
admin theme you're running, and `_one_time_key_message` builds it with
`format_html`, which HTML-escapes its arguments — so nothing in the
generated key (which is entirely `secrets`-generated, but still) can break
out of the `<code>` tag it's rendered inside.

## Extending it for your concrete model

`TenantAPIKeyAdmin` is meant to be subclassed, not used directly:

```python
@admin.register(OrganizationAPIKey)
class OrganizationAPIKeyAdmin(TenantAPIKeyAdmin):
    list_display = TenantAPIKeyAdmin.list_display + ("tenant",)
    list_filter = TenantAPIKeyAdmin.list_filter + ("tenant",)
```

Extending `list_display`/`list_filter` this way keeps the masked-key
column and the readonly protections intact — you're adding to the base
admin, not replacing `save_model` or `masked_key` yourself.

## Try it

- Full API reference: the [README](https://github.com/stackadnan/django-tenant-apikeys#readme)
- A working end-to-end project, including its own `OrganizationAPIKeyAdmin`: [`examples/simple_saas/`](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- See also: [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication)
