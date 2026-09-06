# Metadata

`metadata` is a `JSONField` (default `{}`) for whatever your application
wants to attach to a key. The library stores it and returns it — it does
not read, validate, or act on anything inside it.

```python
instance, raw_key = OrganizationAPIKey.generate_key(
    name="Billing service key",
    tenant=org,
    metadata={
        "owner": "billing-service",
        "plan": "pro",
        "created_by": "admin@example.com",
    },
)

instance.metadata["owner"]  # "billing-service"
```

## What it's for

Anything you'd otherwise bolt onto the key model yourself with a one-off
field: which internal service issued the key, a support ticket reference, a
customer plan tier, an approval trail. `metadata` exists so you don't need
a migration every time you think of one more thing worth recording per key.

It's unstructured on purpose — there's no schema, no required keys, no
validation beyond "must be JSON-serializable" (enforced by `JSONField`
itself, not by this package). If you need a specific value validated or
enforced (like `environment`'s fixed set of choices), that's what
[Environments](environments.md) is for; `metadata` is deliberately the
overflow for everything else.

## Editing it

`metadata` is an ordinary field — set it at creation via `generate_key()`,
update it directly on the instance, or edit it from the
[admin](admin.md#editable-fields), same as any other `JSONField`:

```python
api_key.metadata["plan"] = "enterprise"
api_key.save(update_fields=["metadata"])
```

## Copied on rotation

`rotate()` carries `metadata` over to the replacement key by default, as an
independent copy — mutating the new key's `metadata` after rotation never
reaches back and mutates the original row's:

```python
new_key, raw_key = old_key.rotate()
new_key.metadata["plan"] = "enterprise"
old_key.metadata["plan"]  # unchanged
```

Override it explicitly if the rotated key should carry different metadata:

```python
old_key.rotate(metadata={"owner": "billing-service", "rotated_from": old_key.prefix})
```

## Next

- [Environments](environments.md) — the other, validated, per-key
  attribute this package adds.
- [Key lifecycle](key-lifecycle.md) — what else `rotate()` carries over.
