# django-tenant-apikeys wiki

[django-tenant-apikeys](https://github.com/stackadnan/django-tenant-apikeys)
is a small, framework-agnostic package for issuing API keys to the
tenants/organizations in a multi-tenant Django app — prefix + hashed
secret, per-key scopes, expiration, and throttled last-used tracking, with
first-class Django REST Framework support and a documented Django Ninja
recipe. For install instructions and the full API reference, start with
the [README](https://github.com/stackadnan/django-tenant-apikeys#readme).

This wiki goes deeper on specific topics than the README does. Suggested
reading order below; jump straight to whichever one you need otherwise.

## Start here

1. [Django multi-tenant API key authentication](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-multi%E2%80%90tenant-API-key-authentication) — the core model: why multi-tenant API keys need more than `TokenAuthentication`, and how the prefix+hash, scopes, expiry, and `last_used_at` fields work together.
2. [django-tenant-apikeys vs djangorestframework-api-key: which one do you need](https://github.com/stackadnan/django-tenant-apikeys/wiki/django%E2%80%90tenant%E2%80%90apikeys-vs-djangorestframework%E2%80%90api%E2%80%90key:-which-one-do-you-need) — a factual comparison if you're deciding between the two.

## Using it with Django REST Framework

3. [Scoping API keys per tenant in Django REST Framework](https://github.com/stackadnan/django-tenant-apikeys/wiki/Scoping-API-keys-per-tenant-in-Django-REST-Framework) — `has_scope()`, `HasAPIKeyScope`, and designing a scope taxonomy that ages well.
4. [Testing a custom DRF authentication backend with pytest-django](https://github.com/stackadnan/django-tenant-apikeys/wiki/Testing-a-custom-DRF-authentication-backend-with-pytest%E2%80%90django) — how the package's own test suite proves every rejection path, as a template for testing your own auth backend.

## Using it without DRF

5. [Django Ninja API key auth without DRF](https://github.com/stackadnan/django-tenant-apikeys/wiki/Django-Ninja---API-key-auth-without-DRF) — the framework-agnostic core wired into a Ninja `APIKeyHeader`, line by line.

## Operating keys in production

6. [Rotating and expiring API keys in Django without breaking existing clients](https://github.com/stackadnan/django-tenant-apikeys/wiki/Rotating-and-expiring-API-keys-in-Django-without-breaking-existing-clients) — the overlap pattern: issue new, grace-period the old one, verify the cutover with `last_used_at`.
7. [Throttled last_used_at tracking: avoiding a DB write on every authenticated request](https://github.com/stackadnan/django-tenant-apikeys/wiki/Throttled-last_used_at-tracking:-avoiding-a-DB-write-on-every-authenticated-request) — how `record_usage()` avoids turning a hot endpoint into a write on every request.
8. [One-time secret reveal in Django admin: the pattern behind save_model](https://github.com/stackadnan/django-tenant-apikeys/wiki/One%E2%80%90time-secret-reveal-in-Django-admin:-the-pattern-behind-save_model) — how the admin shows a new secret exactly once, and how to extend it safely for your own concrete model.

## Architecture and security

9. [Multi-tenant Django patterns: shared-schema vs schema-per-tenant, and where API keys fit](https://github.com/stackadnan/django-tenant-apikeys/wiki/Multi%E2%80%90tenant-Django-patterns:-shared%E2%80%90schema-vs-schema%E2%80%90per%E2%80%90tenant,-and-where-API-keys-fit) — where this package's shared-schema design fits, and what changes in a schema-per-tenant setup.
10. [A security checklist for storing API keys in Django](https://github.com/stackadnan/django-tenant-apikeys/wiki/A-security-checklist-for-storing-API-keys-in-Django) — every security decision the package made, as a general checklist for storing API keys in Django whether you use this package or not.

## Elsewhere

- [Full README and API reference](https://github.com/stackadnan/django-tenant-apikeys#readme)
- [A working end-to-end example project](https://github.com/stackadnan/django-tenant-apikeys/tree/main/examples/simple_saas)
- [Issues](https://github.com/stackadnan/django-tenant-apikeys/issues) — bug reports and feature requests
- [Changelog](https://github.com/stackadnan/django-tenant-apikeys/blob/main/CHANGELOG.md)
