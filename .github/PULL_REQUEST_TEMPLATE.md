## What does this change, and why?

<!--
Explain the reasoning, not just the diff — "why" is what's useful in review
and in the git history later. Link an issue if one exists.
-->

## Checklist

- [ ] This PR does one thing. (Unrelated formatting/refactoring belongs in
      a separate PR — see [CONTRIBUTING.md](https://github.com/stackadnan/django-tenant-apikeys/blob/main/CONTRIBUTING.md).)
- [ ] If this changes behavior (not just docs/comments), I added or updated
      a test for it.
- [ ] `pytest --cov=django_tenant_apikeys --cov-report=term-missing` passes
      at 100% coverage.
- [ ] `ruff check .` passes.
- [ ] `mypy django_tenant_apikeys` passes in strict mode.
- [ ] I checked the [README FAQ](https://github.com/stackadnan/django-tenant-apikeys#faq)
      and [SECURITY.md scope section](https://github.com/stackadnan/django-tenant-apikeys/blob/main/SECURITY.md#scope) —
      this isn't something deliberately left out of the core.

## Anything reviewers should look at closely?

<!-- Optional: a tricky edge case, a design trade-off you're unsure about, etc. -->
